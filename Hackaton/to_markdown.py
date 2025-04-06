from docx import Document
import os
import re

def convert_docx_to_markdown(docx_path, output_dir="markdown_files"):
    # Создаем директорию для markdown файлов, если её нет
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Получаем имя файла без расширения
    base_name = os.path.basename(docx_path)
    file_name = os.path.splitext(base_name)[0]
    
    # Создаем путь для выходного markdown файла
    markdown_path = os.path.join(output_dir, f"{file_name}.md")
    
    # Открываем документ
    doc = Document(docx_path)
    
    # Открываем файл для записи
    with open(markdown_path, 'w', encoding='utf-8') as md_file:
        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if not text:
                md_file.write('\n')
                continue
            
            # Определяем стиль параграфа
            style = paragraph.style.name
            
            # Форматируем текст в зависимости от стиля и содержимого
            if text.startswith('Раздел'):
                md_file.write(f'\n# {text}\n\n')
            elif text.startswith('Глава'):
                md_file.write(f'\n## {text}\n\n')
            elif text.startswith('Статья'):
                md_file.write(f'\n### {text}\n\n')
            else:
                # Обрабатываем форматирование внутри параграфа
                formatted_text = ''
                for run in paragraph.runs:
                    if run.bold:
                        formatted_text += f'**{run.text}**'
                    elif run.italic:
                        formatted_text += f'*{run.text}*'
                    else:
                        formatted_text += run.text
                
                md_file.write(f'{formatted_text}\n\n')
    
    print(f"Конвертация завершена. Результат сохранен в {markdown_path}")
    return markdown_path

def convert_all_docx(input_dir="docx", output_dir="markdown_files"):
    """Конвертирует все DOCX файлы в директории"""
    converted_files = []
    
    for filename in os.listdir(input_dir):
        if filename.endswith('.docx') and not filename.startswith('~$'):
            docx_path = os.path.join(input_dir, filename)
            try:
                markdown_path = convert_docx_to_markdown(docx_path, output_dir)
                converted_files.append(markdown_path)
                print(f"Успешно конвертирован файл: {filename}")
            except Exception as e:
                print(f"Ошибка при конвертации файла {filename}: {str(e)}")
    
    return converted_files

if __name__ == "__main__":
    # Конвертируем все файлы
    converted_files = convert_all_docx()
    print("\nКонвертация всех файлов завершена.")
    print(f"Сконвертировано файлов: {len(converted_files)}")