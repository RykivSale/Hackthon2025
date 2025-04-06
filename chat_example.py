import os
import logging
from dotenv import load_dotenv
from chat_pdf import PDFChat

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    try:
        # Load environment variables
        load_dotenv()
        ollama_host = os.getenv('OLLAMA_HOST', 'http://192.168.1.18:11434')
        logger.info(f"Using Ollama host from .env: {ollama_host}")
        
        # Создание экземпляра чата с указанием хоста
        logger.info("Creating PDFChat instance...")
        pdf_chat = PDFChat(ollama_host=ollama_host)
        
        # Загрузка PDF или DOCX
        file_path = r"C:\Users\anton\Desktop\ТЗ пример.pdf"
        logger.info(f"Loading document from: {file_path}")
        if file_path.endswith('.pdf'):
            pdf_chat.load_pdf(file_path)
        elif file_path.endswith('.docx'):
            pdf_chat.load_docx(file_path)
        
        # Пример диалога
        questions = [
            "Запомни число 3",
            "Какое число запомнил?",
            "Какое число запомнил?"
        ]
        
        # Задаем вопросы и получаем ответы
        for question in questions:
            logger.info(f"Asking question: {question}")
            print(f"\nQ: {question}")
            response = pdf_chat.ask(question)
            print(f"A: {response}")
        
        # Получаем историю чата
        logger.info("Retrieving chat history...")
        print("\nChat History:")
        chat_history = pdf_chat.get_chat_history()
        for message in chat_history:
            print(f"\nQ: {message['question']}")
            print(f"A: {message['answer']}")
        
        # Очищаем историю чата
        logger.info("Clearing chat history...")
        pdf_chat.clear_chat_history()
    except Exception as e:
        logger.error(f"An error occurred: {e}")

if __name__ == "__main__":
    main()