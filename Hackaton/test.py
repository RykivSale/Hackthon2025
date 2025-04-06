import os
import re
import json
from typing import Dict, List, Optional

class LegalDocumentParser:
    def __init__(self):
        # Расширенные паттерны для поиска структурных элементов
        self.patterns = {
            'section': r'^(?:#\s*)?(?:Раздел\s+([IVX]+)\.?\s*(.*?)$|РАЗДЕЛ\s+([IVX]+)\.?\s*(.*?)$|ГЛАВА\s+([IVX]+)\.?\s*(.*?)$)',
            'chapter': r'^(?:##\s*)?(?:Глава\s+(\d+)\.?\s*(.*?)$|ГЛАВА\s+(\d+)\.?\s*(.*?)$)',
            'article': r'^(?:###\s*)?(?:Статья\s+(\d+(?:\.\d+)?)\.?\s*(.*?)$|СТАТЬЯ\s+(\d+(?:\.\d+)?)\.?\s*(.*?)$)',
            'part': r'^(?:(\d+)\.|\((\d+)\))\s+(.+)$',
            'subpart': r'^(\d+\.\d+)\s+(.+)$'
        }

    def parse_markdown_file(self, file_path: str) -> Dict:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        lines = content.split('\n')
        
        document_structure = {
            'имя_файла': os.path.basename(file_path),
            'разделы': [],
            'метаданные': self._extract_metadata(content)
        }

        current_section = None
        current_chapter = None
        current_article = None
        current_content = []
        has_sections = False

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Проверяем раздел
            section_match = re.match(self.patterns['section'], line)
            if section_match:
                has_sections = True
                # Сохраняем содержимое предыдущей статьи, если есть
                if current_article and current_content:
                    current_article['содержимое'] = self._process_content(current_content)
                    current_content = []

                section_num = section_match.group(1) or section_match.group(3) or section_match.group(5)
                section_title = section_match.group(2) or section_match.group(4) or section_match.group(6)
                section = {
                    'номер': section_num,
                    'название': section_title.strip(),
                    'главы': []
                }
                document_structure['разделы'].append(section)
                current_section = section
                current_chapter = None
                current_article = None
                continue

            # Проверяем главу
            chapter_match = re.match(self.patterns['chapter'], line)
            if chapter_match:
                # Сохраняем содержимое предыдущей статьи, если есть
                if current_article and current_content:
                    current_article['содержимое'] = self._process_content(current_content)
                    current_content = []

                chapter_num = chapter_match.group(1) or chapter_match.group(3)
                chapter_title = chapter_match.group(2) or chapter_match.group(4)
                chapter = {
                    'номер': chapter_num,
                    'название': chapter_title.strip(),
                    'статьи': []
                }
                
                if current_section:
                    current_section['главы'].append(chapter)
                else:
                    # Если нет раздела, создаем главы на верхнем уровне
                    if 'главы' not in document_structure:
                        document_structure['главы'] = []
                    document_structure['главы'].append(chapter)
                
                current_chapter = chapter
                current_article = None
                continue

            # Проверяем статью
            article_match = re.match(self.patterns['article'], line)
            if article_match:
                # Сохраняем содержимое предыдущей статьи, если есть
                if current_article and current_content:
                    current_article['содержимое'] = self._process_content(current_content)
                    current_content = []

                article_num = article_match.group(1) or article_match.group(3)
                article_title = article_match.group(2) or article_match.group(4)
                article = {
                    'номер': article_num,
                    'название': article_title.strip(),
                    'содержимое': {}
                }
                
                if current_chapter:
                    current_chapter['статьи'].append(article)
                else:
                    # Если нет главы, создаем статьи на верхнем уровне
                    if 'статьи' not in document_structure:
                        document_structure['статьи'] = []
                    document_structure['статьи'].append(article)
                
                current_article = article
                continue

            # Если это обычный текст и у нас есть текущая статья
            if current_article and line:
                current_content.append(line)

        # Сохраняем содержимое последней статьи
        if current_article and current_content:
            current_article['содержимое'] = self._process_content(current_content)

        # Если в документе нет разделов, удаляем пустой список разделов
        if not has_sections and not document_structure['разделы']:
            del document_structure['разделы']

        return document_structure

    def _extract_metadata(self, content: str) -> Dict:
        """Извлекает метаданные из документа"""
        metadata = {}
        
        # Поиск даты документа
        date_pattern = r'от\s+(\d{1,2}\s+[а-яА-Я]+\s+\d{4}\s+года|\d{1,2}\.\d{1,2}\.\d{4})'
        date_match = re.search(date_pattern, content)
        if date_match:
            metadata['дата'] = date_match.group(1)
            
        # Поиск номера документа
        number_pattern = r'№?\s*(\d+[-\w]*)'
        number_match = re.search(number_pattern, content)
        if number_match:
            metadata['номер'] = number_match.group(1)
            
        # Поиск типа документа
        doc_type_pattern = r'^(?:ПОСТАНОВЛЕНИЕ|ПРИКАЗ|ФЕДЕРАЛЬНЫЙ ЗАКОН|РЕШЕНИЕ)'
        doc_type_match = re.search(doc_type_pattern, content, re.MULTILINE)
        if doc_type_match:
            metadata['тип'] = doc_type_match.group(0).title()
            
        return metadata

    def _process_content(self, content_lines: List[str]) -> Dict:
        """Обрабатывает содержимое статьи, разделяя на части и подпункты"""
        processed_content = {
            'текст': [],
            'части': [],
            'подпункты': []
        }
        
        current_part = None
        current_subpart = None
        current_part_content = []
        current_subpart_content = []
        
        for line in content_lines:
            # Проверяем, является ли строка частью статьи
            part_match = re.match(self.patterns['part'], line)
            subpart_match = re.match(self.patterns['subpart'], line)
            
            if part_match:
                # Сохраняем предыдущую часть, если есть
                if current_part and current_part_content:
                    current_part['текст'] = ' '.join(current_part_content)
                    processed_content['части'].append(current_part)
                    current_part_content = []
                
                part_num = part_match.group(1) or part_match.group(2)
                part_text = part_match.group(3)
                current_part = {
                    'номер': part_num,
                    'текст': part_text,
                    'подпункты': []
                }
                processed_content['части'].append(current_part)
                current_part = None
            elif subpart_match:
                # Сохраняем предыдущий подпункт, если есть
                if current_subpart and current_subpart_content:
                    current_subpart['текст'] = ' '.join(current_subpart_content)
                    if current_part:
                        current_part['подпункты'].append(current_subpart)
                    else:
                        processed_content['подпункты'].append(current_subpart)
                    current_subpart_content = []
                
                subpart_num = subpart_match.group(1)
                subpart_text = subpart_match.group(2)
                current_subpart = {
                    'номер': subpart_num,
                    'текст': subpart_text
                }
                if current_part:
                    current_part['подпункты'].append(current_subpart)
                else:
                    processed_content['подпункты'].append(current_subpart)
                current_subpart = None
            else:
                if current_subpart:
                    current_subpart_content.append(line)
                elif current_part:
                    current_part_content.append(line)
                else:
                    processed_content['текст'].append(line)

        # Сохраняем последнюю часть и подпункт, если есть
        if current_part and current_part_content:
            current_part['текст'] = ' '.join(current_part_content)
            processed_content['части'].append(current_part)
            
        if current_subpart and current_subpart_content:
            current_subpart['текст'] = ' '.join(current_subpart_content)
            if current_part:
                current_part['подпункты'].append(current_subpart)
            else:
                processed_content['подпункты'].append(current_subpart)

        # Объединяем основной текст
        processed_content['текст'] = ' '.join(processed_content['текст'])

        return processed_content

    def process_directory(self, directory: str) -> List[Dict]:
        """Обрабатывает все markdown файлы в указанной директории"""
        results = []
        
        for filename in os.listdir(directory):
            if filename.endswith('.md'):
                file_path = os.path.join(directory, filename)
                try:
                    print(f"Обработка файла: {filename}")
                    result = self.parse_markdown_file(file_path)
                    results.append(result)
                    print(f"Успешно обработан файл: {filename}")
                except Exception as e:
                    print(f"Ошибка при обработке файла {filename}: {str(e)}")
        
        return results

def save_results(results: List[Dict], output_file: str):
    """Сохраняет результаты в JSON файл"""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

def main():
    parser = LegalDocumentParser()
    
    # Путь к директории с markdown файлами
    markdown_directory = "markdown_files"
    
    # Обработка документов
    results = parser.process_directory(markdown_directory)
    
    # Сохранение результатов
    output_file = "parsed_legal_documents.json"
    save_results(results, output_file)
    
    print(f"Обработка завершена. Результаты сохранены в {output_file}")

if __name__ == "__main__":
    main()