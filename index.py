import asyncio
import logging
from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters.command import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from sqlalchemy.ext.asyncio import async_session, AsyncSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.dispatcher.dispatcher import Dispatcher
from DB import User, History, create_tables as init_db, async_session as async_session_maker, create_history, get_user_history
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from typing import Any, Awaitable, Callable, Dict
from sqlalchemy import select
import os
from chat_pdf import PDFChat
from dotenv import load_dotenv
import json
from langchain.graphs import NetworkxEntityGraph
from langchain.graphs.graph_store import GraphStore
from langchain.schema import Document
from langchain.text_splitter import CharacterTextSplitter
from langchain.chains import GraphQAChain
from langchain.chat_models import ChatOpenAI
from Hackaton.legal_qa import LegalQASystem
from langchain.chat_models import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage

# Создаем роутер
router = Router()


# Класс для состояний бота
class BotStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_file = State()  # New state for file upload
    analytics_mode = State()
    chat_tz = State()


# Хранение истории анализов (в реальном проекте лучше использовать базу данных)
analyses = {}


# Клавиатуры
def get_analytics_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Получить рекомендуемые НПА", callback_data="get_recommendations")
        ],
        [
            InlineKeyboardButton(text="Анализ текста ТЗ", callback_data="analyze_tz_text")
        ],
        [
            InlineKeyboardButton(text="Выход из режима аналитики", callback_data="exit_analytics"),
            InlineKeyboardButton(text="Чат по ТЗ", callback_data="chat_tz")
        ]
    ])
    return keyboard


def get_history_keyboard():
    buttons = []
    for analysis_id, analysis in analyses.items():
        buttons.append([InlineKeyboardButton(
            text=f"Анализ {analysis_id}",
            callback_data=f"analysis_{analysis_id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_analysis_options_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Режим аналитики", callback_data="start_analytics"),
            InlineKeyboardButton(text="Удаление анализа", callback_data="delete_analysis"),
            InlineKeyboardButton(text="Назад", callback_data="back_to_history")
        ]
    ])
    return keyboard


# Обработчики команд


@router.message(Command("start"))
@router.message(F.text.lower() == "регистрация")
async def register_user(message: Message, session: AsyncSession):
    """Регистрация пользователя в базе данных"""
    user_id = message.from_user.id
    username = message.from_user.full_name

    try:
        # Проверяем, есть ли пользователь уже в базе по users_id
        existing_user = await session.execute(select(User).where(User.users_id == user_id))
        existing_user = existing_user.scalar_one_or_none()
        
        if existing_user:
            await message.answer("🔄 Вы уже зарегистрированы!")
            return

        # Создаем нового пользователя
        new_user = User(
            users_id=user_id,
            users_name=username
        )

        session.add(new_user)
        await session.commit()

        await message.answer(
            "✅ Регистрация успешна!\n"
            f"ID: {user_id}\n"
            f"Имя: {username}"
        )

    except Exception as e:
        await session.rollback()
        await message.answer("❌ Ошибка при регистрации. Попробуйте позже.")
        print(f"Ошибка регистрации: {e}")


@router.message(BotStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext, session: AsyncSession):
    user_name = message.text
    user_id = message.from_user.id

    if len(user_name) < 2:
        await message.reply("Имя должно содержать хотя бы 2 символа. Попробуйте еще раз:")
        return

    # Здесь исправляем поле на правильное имя из модели User
    new_user = User(
        users_id=user_id,  # Используйте правильное имя поля из вашей модели
        users_name=user_name
    )
    session.add(new_user)
    await session.commit()

    await message.reply(
        f"Отлично, {user_name}! Добро пожаловать! Используйте /help для получения списка команд."
    )
    await state.clear()


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = """
    🤖 Описание работы сервиса:

    /upload_tech - Запуск режима аналитики
    /history - Просмотр предыдущих анализов
    /help - Показать это сообщение

    В режиме аналитики вы можете:
    - Общаться с ботом по ТЗ
    - Выйти из режима аналитики

    В истории анализов вы можете:
    - Просматривать прошлые анализы
    - Удалять анализы
    - Запускать режим аналитики для выбранного анализа
    """
    await message.reply(help_text)


@router.message(Command("upload_tech"))
async def cmd_upload_tech(message: Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_file)
    await message.reply("Пожалуйста, загрузите файл технического задания в формате PDF или DOCX.")


@router.message(BotStates.waiting_for_file)
async def process_tech_doc(message: Message, state: FSMContext, session: AsyncSession):
    if not message.document:
        await message.reply("Пожалуйста, отправьте документ (PDF или DOCX файл).")
        return

    file_name = message.document.file_name.lower()
    if not file_name.endswith(('.pdf', '.docx')):
        await message.reply("Неверный формат файла. Пожалуйста, отправьте документ в формате PDF или DOCX.")
        return

    thinking_message = await message.reply("Думаю...")  # Notify the user about processing

    try:
        # Download the file
        file = await message.bot.get_file(message.document.file_id)
        downloaded_file = await message.bot.download_file(file.file_path)
        
        # Save the file locally
        local_file_path = f"temp_{message.document.file_id}{os.path.splitext(file_name)[1]}"
        with open(local_file_path, 'wb') as f:
            f.write(downloaded_file.read())
        ollama_host = 'http://192.168.1.18:11434'
        pdf_chat = PDFChat(ollama_host=ollama_host)
        
        # Load the document based on its type
        if file_name.endswith('.pdf'):
            pdf_chat.load_pdf(local_file_path)
        else:
            pdf_chat.load_docx(local_file_path)

        # Store PDFChat instance in state
        await state.update_data(pdf_chat=pdf_chat)
        
        # Create history record
        user_id = message.from_user.id
        history_record = await create_history(
            session=session,
            users_id=user_id,
            path_to_tz=local_file_path,
            path_to_analyze="pending"
        )
        await session.commit()
        
        # Clean up the temporary file
        os.remove(local_file_path)
        
        await thinking_message.delete()  # Remove 'Думаю...' after processing
        await message.reply(
            "✅ Файл успешно загружен и обработан.\nРежим аналитики активирован.",
            reply_markup=get_analytics_keyboard()
        )
    except Exception as e:
        await session.rollback()
        await thinking_message.delete()  # Remove 'Думаю...' in case of an error
        await message.reply("❌ Произошла ошибка при обработке файла. Пожалуйста, попробуйте снова.")
        logging.error(f"File processing error: {str(e)}")
        await state.set_state(BotStates.waiting_for_file)
        if 'local_file_path' in locals():
            try:
                os.remove(local_file_path)
            except:
                pass


@router.message(Command("history"))
async def cmd_history(message: types.Message, session: AsyncSession):
    user_id = message.from_user.id
    
    try:
        # Получаем историю пользователя из базы данных
        user_history = await get_user_history(session, users_id=user_id)
        
        if not user_history:
            await message.reply("История анализов пуста.")
            return

        # Создаем клавиатуру с историей
        buttons = []
        for history in user_history:
            buttons.append([InlineKeyboardButton(
                text=f"Анализ #{history.id}",
                callback_data=f"analysis_{history.id}"
            )])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.reply("Предыдущие анализы:", reply_markup=keyboard)
        
    except Exception as e:
        await message.reply(f"Ошибка при получении истории: {e}")


# Обработчики callback'ов
@router.callback_query(F.data == "chat_tz")
async def process_chat_tz(callback_query: types.CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.chat_tz)
    await callback_query.message.reply("Режим чата по ТЗ активирован. Напишите ваше сообщение.")
    await callback_query.answer()


@router.callback_query(F.data == "exit_analytics")
async def process_exit_analytics(callback_query: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback_query.message.reply("Режим аналитики деактивирован.")
    await callback_query.answer()


@router.callback_query(F.data.startswith("analysis_"))
async def process_analysis_selection(callback_query: types.CallbackQuery):
    analysis_id = callback_query.data.split("_")[1]
    await callback_query.message.reply(
        f"Выбран анализ {analysis_id}",
        reply_markup=get_analysis_options_keyboard()
    )
    await callback_query.answer()


@router.callback_query(F.data == "start_analytics")
async def process_start_analytics(callback_query: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    user_id = callback_query.from_user.id
    
    try:
        # Создаем запись в истории
        history_record = await create_history(
            session=session,
            users_id=user_id,
            path_to_tz="path/to/tz",  # Здесь нужно указать реальный путь к ТЗ
            path_to_analyze="path/to/analysis"  # Здесь нужно указать реальный путь к анализу
        )
        await session.commit()
        
        await state.set_state(BotStates.analytics_mode)
        await callback_query.message.reply(
            "Режим аналитики активирован.",
            reply_markup=get_analytics_keyboard()
        )
    except Exception as e:
        await session.rollback()
        await callback_query.message.reply(f"Ошибка при создании записи в истории: {e}")
    
    await callback_query.answer()


@router.callback_query(F.data == "delete_analysis")
async def process_delete_analysis(callback_query: types.CallbackQuery):
    analysis_id = callback_query.message.text.split()[-1]
    if analysis_id in analyses:
        del analyses[analysis_id]
        await callback_query.message.reply("Анализ удален.")
    await callback_query.message.reply(
        "Предыдущие анализы:",
        reply_markup=get_history_keyboard()
    )
    await callback_query.answer()


@router.callback_query(F.data == "back_to_history")
async def process_back_to_history(callback_query: types.CallbackQuery):
    await callback_query.message.reply(
        "Предыдущие анализы:",
        reply_markup=get_history_keyboard()
    )
    await callback_query.answer()


@router.callback_query(F.data == "get_recommendations")
async def process_get_recommendations(callback_query: CallbackQuery, state: FSMContext):
    """
    Обработчик для получения рекомендаций по НПА на основе загруженного ТЗ
    """
    thinking_msg = await callback_query.message.answer("Думаю...")
    
    try:
        # Get PDFChat instance and extracted text from state
        data = await state.get_data()
        pdf_chat = data.get('pdf_chat')
        
        if not pdf_chat:
            await thinking_msg.edit_text("❌ Ошибка: документ не загружен. Пожалуйста, загрузите документ через /upload_tech")
            return

        # First agent: Generate a focused legal question based on the technical specification
        query_prompt = """
        Проанализируй техническое задание и сформулируй юридический вопрос в следующем формате:
        "Я хочу [действие/цель из ТЗ] в [место/условия из ТЗ], какие законы и нормативные акты необходимо соблюдать?"
        
        Например: "Я хочу открыть кофейню в Ростове-на-Дону, какие законы мне нужно соблюдать?"
        """
        legal_question = pdf_chat.ask(query_prompt)
        
        # Initialize LegalQASystem
        qa_system = LegalQASystem()
        qa_system.load_documents("Hackaton\parsed_legal_documents.json")
        
        # Get recommendations using the generated legal question
        results = qa_system.answer_question(legal_question)
        
        if results.get("ответы"):

                        
            # Format the response
            response = f"🔍 Сформулированный вопрос:\n{legal_question}\n\n"
            response += "📚 Рекомендуемые нормативно-правовые акты:\n\n"
            for i, answer in enumerate(results["ответы"], 1):
                             # Convert confidence to text format
                confidence_text = "маловажно"
                if answer["уверенность"] > 0.9:
                    confidence_text = "очень важно"
                elif answer["уверенность"] > 0.8:
                    confidence_text = "важно"
                response += f"{i}. {answer['документ']}\n"
                response +=     f"Релевантность: {confidence_text}\n\n"
                response += f"Обоснование: {answer['ответ']}\n\n"
        else:
            response = "❌ Не найдено релевантных нормативно-правовых актов."
        
        await thinking_msg.edit_text(response)
        
    except Exception as e:
        logging.error(f"Error getting NPA recommendations: {str(e)}")
        await thinking_msg.edit_text("❌ Произошла ошибка при получении рекомендаций. Пожалуйста, попробуйте снова.")


@router.callback_query(F.data == "analyze_tz_text")
async def analyze_tz_text(callback_query: CallbackQuery, state: FSMContext):
    """
    Анализирует текст ТЗ по абзацам и добавляет рекомендации со ссылками на НПА
    """
    thinking_msg = await callback_query.message.answer("Анализирую текст ТЗ...")
    
    try:
        # Get PDFChat instance from state
        data = await state.get_data()
        pdf_chat = data.get('pdf_chat')
        
        if not pdf_chat:
            await thinking_msg.edit_text("❌ Ошибка: документ не загружен. Пожалуйста, загрузите документ через /upload_tech")
            return

        # Initialize LegalQASystem
        qa_system = LegalQASystem()
        qa_system.load_documents("Hackaton/parsed_legal_documents.json")
        
        # Get the full text and split into sections and paragraphs
        full_text = pdf_chat.get_document_text()
        
        # Split text into sections by double newlines and handle potential section headers
        sections = []
        current_section = []
        
        for line in full_text.split('\n'):
            line = line.strip()
            if not line:
                if current_section:
                    sections.append('\n'.join(current_section))
                    current_section = []
            else:
                current_section.append(line)
        
        if current_section:
            sections.append('\n'.join(current_section))
        
        # Set to track unique NPAs used in analysis
        used_npas = set()
        
        # Build HTML response
        html_response = "<h2>Анализ технического задания</h2>"
        
        # Analyze each section
        for section in sections:
            if not section.strip():
                continue
            
            # Check if the section starts with a number (likely a section header)
            lines = section.split('\n')
            first_line = lines[0]
            
            # If it's a section header, format it accordingly
            if any(char.isdigit() for char in first_line[:2]):
                html_response += f"<h3 class='section-header'>{first_line}</h3>"
                section_content = '\n'.join(lines[1:])
            else:
                section_content = section
            
            # Add section content
            if section_content.strip():
                html_response += f"<div class='section-content'>"
                html_response += f"<p class='paragraph'>{section_content}</p>"
                
                # Check for legal violations
                legal_question = f"Проверь следующий текст на нарушения требований законодательства: {section_content}"
                legal_results = qa_system.answer_question(legal_question)
                
                violations = []
                if legal_results.get("ответы"):
                    for answer in legal_results["ответы"]:
                        if answer["уверенность"] > 0.7:
                            doc = answer["документ"]
                            chapter = answer.get("глава", "")
                            article = answer.get("статья", "")
                            reference = f"{doc} {chapter} {article}".strip()
                            
                            used_npas.add(doc)
                            
                            # Convert confidence to text format
                            confidence_text = "маловажно"
                            if answer["уверенность"] > 0.9:
                                confidence_text = "очень важно"
                            elif answer["уверенность"] > 0.8:
                                confidence_text = "важно"
                            
                            if "нарушен" in answer["ответ"].lower() or "требует" in answer["ответ"].lower():
                                violations.append(
                                    f"<div class='violation'>"
                                    f"<em><strong>⚠️ {answer['ответ']}</strong></em><br>"
                                    f"<span class='reference'>📚 {reference}</span><br>"
                                    f"<span class='relevance'>Релевантность: {confidence_text}</span>"
                                    f"</div>"
                                )
                
                if violations:
                    html_response += "\n".join(violations)
                
                # First add used NPAs before style recommendations
                if used_npas:
                    html_response += "<div class='used-npas'>"
                    html_response += "<h3>Использованные нормативно-правовые акты:</h3>"
                    html_response += "<ul class='npa-list'>"
                    for npa in sorted(used_npas):
                        html_response += f"<li>{npa}</li>"
                    html_response += "</ul></div>"
                
                # Then check for stylistic issues
                style_question = f"Проверь следующий текст на стилистические ошибки и неточности формулировок: {section_content}"
                style_analysis = pdf_chat.ask(style_question)
                
                if style_analysis and ("ошибк" in style_analysis.lower() or "неточност" in style_analysis.lower()):
                    html_response += (
                        f"<div class='style-note'>"
                        f"<em>💡 Стилистическая рекомендация:</em><br>"
                        f"{style_analysis}"
                        f"</div>"
                    )
                
                html_response += "</div>"
        
        # Get overall assessment of the document
        overall_assessment = pdf_chat.ask("""
        Дай общую оценку техническому заданию по следующим критериям:
        1. Полнота и четкость требований
        2. Соответствие нормативным документам
        3. Стилистическая грамотность
        4. Реализуемость требований
        5. Общие рекомендации по улучшению
        
        Формат ответа: по каждому пункту дай краткую оценку в 1-2 предложения.
        """)
        
        # Add overall assessment section
        if overall_assessment:
            html_response += """
            <div class='overall-assessment'>
                <h3>Общее заключение по документу</h3>
                <div class='assessment-content'>
                    """ + overall_assessment.replace('\n', '<br>') + """
                </div>
            </div>
            """
        
        # Save the HTML file
        output_path = "tz_analysis.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{ 
                        font-family: Arial, sans-serif; 
                        margin: 40px;
                        line-height: 1.6;
                        max-width: 1200px;
                        margin-left: auto;
                        margin-right: auto;
                        color: #333;
                        background-color: #f9f9f9;
                    }}
                    h2 {{ 
                        color: #2c3e50;
                        margin-bottom: 40px;
                        padding-bottom: 15px;
                        border-bottom: 2px solid #eee;
                        text-align: center;
                    }}
                    h3 {{ 
                        color: #34495e; 
                        margin-top: 40px;
                        margin-bottom: 20px;
                    }}
                    .section-header {{
                        background-color: #edf2f7;
                        padding: 15px;
                        border-radius: 6px;
                        margin-top: 40px;
                        font-weight: bold;
                        color: #2d3748;
                    }}
                    .section-content {{
                        margin: 25px 0;
                        padding: 0 20px;
                    }}
                    .paragraph {{
                        white-space: pre-line;
                        background-color: white;
                        padding: 25px;
                        margin: 20px 0;
                        border-radius: 8px;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                        border-left: 4px solid #95a5a6;
                    }}
                    .violation {{ 
                        background-color: #fff5f5;
                        padding: 20px;
                        margin: 15px 0;
                        border-radius: 8px;
                        border-left: 4px solid #fc8181;
                    }}
                    .violation strong {{
                        color: #c53030;
                    }}
                    .reference {{
                        display: block;
                        margin-top: 10px;
                        color: #4a5568;
                        font-size: 0.9em;
                    }}
                    .relevance {{
                        display: block;
                        margin-top: 5px;
                        color: #718096;
                        font-size: 0.85em;
                    }}
                    .style-note {{
                        background-color: #ebf8ff;
                        padding: 20px;
                        margin: 15px 0;
                        border-radius: 8px;
                        border-left: 4px solid #4299e1;
                    }}
                    .style-note em {{
                        color: #2b6cb0;
                    }}
                    .used-npas {{
                        background-color: white;
                        padding: 30px;
                        border-radius: 12px;
                        margin-top: 60px;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                    }}
                    .npa-list {{
                        list-style-type: none;
                        padding-left: 0;
                    }}
                    .npa-list li {{
                        padding: 12px 20px;
                        border-bottom: 1px solid #edf2f7;
                        color: #4a5568;
                    }}
                    .npa-list li:last-child {{
                        border-bottom: none;
                    }}
                    .overall-assessment {{
                        background-color: #f0f9ff;
                        padding: 30px;
                        border-radius: 12px;
                        margin: 40px 0;
                        border: 1px solid #bae6fd;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                    }}
                    .assessment-content {{
                        padding: 20px;
                        background-color: white;
                        border-radius: 8px;
                        line-height: 1.8;
                    }}
                    .assessment-content br {{
                        margin-bottom: 10px;
                    }}
                    em {{ font-style: italic; }}
                    strong {{ font-weight: bold; }}
                </style>
            </head>
            <body>
            {html_response}
            </body>
            </html>
            """)

        # Send the file
        from aiogram.types import FSInputFile
        document = FSInputFile(output_path, filename="Анализ_ТЗ.html")
        await callback_query.message.answer_document(
            document,
            caption="✅ Анализ ТЗ завершен. Результаты в HTML файле."
        )
        await thinking_msg.delete()
        
    except Exception as e:
        logging.error(f"Error analyzing TZ text: {str(e)}")
        await thinking_msg.edit_text("❌ Произошла ошибка при анализе ТЗ. Пожалуйста, попробуйте снова.")


# Эхо-функция для режима чата по ТЗ
@router.message(BotStates.chat_tz)
async def handle_chat_message(message: Message, state: FSMContext):
    # Get PDFChat instance from state
    data = await state.get_data()
    pdf_chat = data.get('pdf_chat')
    
    if not pdf_chat:
        await message.reply("❌ Ошибка: документ не загружен. Пожалуйста, загрузите документ через /upload_tech")
        return
    
    thinking_message = await message.reply("Думаю...")  # Notify the user about processing

    try:
        # Get response from PDFChat
        response = pdf_chat.ask(message.text)
        await thinking_message.edit_text(response)  # Replace 'Думаю...' with the response
    except Exception as e:
        logging.error(f"Error in chat processing: {str(e)}")
        await thinking_message.edit_text("❌ Произошла ошибка при обработке вашего вопроса. Пожалуйста, попробуйте еще раз.")


# Function to filter documents based on ТЗ keywords
def filter_documents_by_tz(json_file_path, keywords):
    """
    Фильтрует документы из JSON по ключевым словам, связанным с ТЗ.

    :param json_file_path: Путь к JSON-файлу с документами.
    :param keywords: Список ключевых слов для фильтрации.
    :return: Список документов, соответствующих ТЗ.
    """
    with open(json_file_path, "r", encoding="utf-8") as file:
        data = json.load(file)

    filtered_documents = []

    for document in data.get("документы", []):
        file_name = document.get("имя_файла", "").lower()
        if any(keyword.lower() in file_name for keyword in keywords):
            filtered_documents.append(document)

    return filtered_documents

# Example usage during ТЗ upload
@router.message(BotStates.analytics_mode)
async def analyze_tz_documents(message: Message, state: FSMContext):
    """
    Анализирует документы из JSON на соответствие ТЗ.
    """
    await message.reply("Думаю...")

    try:
        # Keywords related to the uploaded ТЗ
        tz_keywords = ["кодекс", "градостроительный", "водный", "гост"]

        # Path to the JSON file
        json_path = "parsed_legal_documents (2).json"

        # Filter documents
        relevant_documents = filter_documents_by_tz(json_path, tz_keywords)

        # Respond with the results
        if relevant_documents:
            response = f"Найдено {len(relevant_documents)} документов, соответствующих ТЗ:\n"
            response += "\n".join([doc.get("имя_файла", "Без имени") for doc in relevant_documents])
        else:
            response = "Не найдено документов, соответствующих ТЗ."

        await message.reply(response)
    except Exception as e:
        logging.error(f"Error analyzing ТЗ documents: {str(e)}")
        await message.reply("❌ Произошла ошибка при анализе документов. Пожалуйста, попробуйте снова.")


# Function to fetch recommendations for NPA using LangChain
def fetch_npa_recommendations(json_file_path, keywords):
    """
    Использует LangChain для анализа JSON и получения рекомендаций по НПА.

    :param json_file_path: Путь к JSON-файлу с документами.
    :param keywords: Список ключевых слов для фильтрации.
    :return: Список названий документов, соответствующих ТЗ.
    """
    # Создаем граф из JSON
    graph = NetworkxEntityGraph()

    with open(json_file_path, "r", encoding="utf-8") as file:
        data = json.load(file)

    for document in data.get("документы", []):
        file_name = document.get("имя_файла", "").lower()
        if any(keyword.lower() in file_name for keywords in keywords):
            graph.add_node(file_name)

    # Формируем запрос для поиска документов
    query = """
    MATCH (doc)
    WHERE """ + " OR ".join([f"doc.имя_файла CONTAINS '{keyword}'" for keyword in keywords]) + """
    RETURN doc.имя_файла
    """

    # Выполняем запрос
    results = graph.query(query)

    # Извлекаем названия документов
    return [result["doc.имя_файла"] for result in results]


@router.callback_query(F.data == "get_npa_recommendations")
async def get_npa_recommendations(callback_query: CallbackQuery):
    """
    Обработчик для получения рекомендаций по НПА.
    """
    await callback_query.message.reply("Думаю...")

    try:
        # Keywords related to the uploaded ТЗ
        tz_keywords = ["кодекс", "градостроительный", "водный", "гост"]

        # Path to the JSON file
        json_path = "parsed_legal_documents (2).json"

        # Fetch recommendations using LangChain
        recommendations = fetch_npa_recommendations(json_path, tz_keywords)

        # Create inline keyboard with recommendations
        if recommendations:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=doc, callback_data=f"npa_{i}")]
                for i, doc in enumerate(recommendations)
            ])
            await callback_query.message.reply("Рекомендации по НПА:", reply_markup=keyboard)
        else:
            await callback_query.message.reply("Не найдено документов, соответствующих ТЗ.")
    except Exception as e:
        logging.error(f"Error fetching NPA recommendations: {str(e)}")
        await callback_query.message.reply("❌ Произошла ошибка при получении рекомендаций. Пожалуйста, попробуйте снова.")


# Функция запуска бота
async def main():
    # Загружаем токен бота из переменной окружения или используем заданный
    BOT_TOKEN = "8097160235:AAF0_dJuMn_jxRmZJDsMxUVIpsOGj6-MHRc"  # Замените на ваш токен

    # Инициализируем базу данных
    await init_db()

    # Инициализируем бота и диспетчер
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Инициализируем PDFChat
    ollama_host = 'http://192.168.1.18:11434'
    pdf_chat = PDFChat(ollama_host=ollama_host)

    # Сохраняем PDFChat в data для использования в обработчиках
    dp.update.middleware(DatabaseMiddleware())
    dp.update.middleware(PDFChatMiddleware(pdf_chat))

    # Регистрируем middleware
    dp.update.middleware(DatabaseMiddleware())

    # Регистрируем роутер
    dp.include_router(router)

    # Запускаем бота
    await dp.start_polling(bot)


class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        async with async_session_maker() as session:
            data["session"] = session
            result = await handler(event, data)
        return result


class PDFChatMiddleware(BaseMiddleware):
    def __init__(self, pdf_chat: PDFChat):
        self.pdf_chat = pdf_chat

    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        data["pdf_chat"] = self.pdf_chat
        return await handler(event, data)


if __name__ == '__main__':
    asyncio.run(main())