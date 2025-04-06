import torch
from transformers import AutoTokenizer, AutoModel
import numpy as np
import json
from typing import List, Dict, Any
import logging
import os

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class LegalQASystem:
    def __init__(self):
        try:
            # Set device to GPU if available
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            logger.info(f"Используется устройство: {self.device}")
            
            # Load model and move to appropriate device
            self.model_name = "DeepPavlov/rubert-base-cased"
            logger.info(f"Загрузка токенизатора из {self.model_name}")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            
            logger.info(f"Загрузка модели из {self.model_name}")
            self.model = AutoModel.from_pretrained(self.model_name).to(self.device)
            
            self.documents = []
            self.document_embeddings = None
            logger.info("Система успешно инициализирована")
        except Exception as e:
            logger.error(f"Ошибка при инициализации системы: {str(e)}")
            raise
        
    def load_documents(self, file_path: str) -> None:
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Файл {file_path} не найден")
                
            logger.info(f"Загрузка документов из {file_path}")
            with open(file_path, 'r', encoding='utf-8') as f:
                self.documents = json.load(f)
            logger.info(f"Загружено {len(self.documents)} документов")
            self._compute_embeddings()
        except Exception as e:
            logger.error(f"Ошибка при загрузке документов: {str(e)}")
            raise

    def _compute_embeddings(self) -> None:
        texts = [doc.get("имя_файла", "") for doc in self.documents]
        embeddings = []
        
        with torch.no_grad():
            for text in texts:
                inputs = self.tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
                # Move inputs to device
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                
                outputs = self.model(**inputs)
                embedding = outputs.last_hidden_state.mean(dim=1)
                embeddings.append(embedding.cpu().numpy())  # Move back to CPU for numpy operations
        
        self.document_embeddings = np.vstack(embeddings)

    def _compute_similarity(self, query_embedding: np.ndarray) -> np.ndarray:
        return np.dot(self.document_embeddings, query_embedding.T).flatten()

    def answer_question(self, question: str) -> Dict[str, Any]:
        try:
            if not self.documents:
                raise ValueError("Документы не загружены")
            question = f"""
            Дай максимально развернутый ответ. Ответ верни в md формате.
            {question}
            """
            logger.info(f"Обработка вопроса: {question}")
            
            with torch.no_grad():
                inputs = self.tokenizer(question, return_tensors="pt", padding=True, truncation=True, max_length=512)
                # Move inputs to device
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                
                outputs = self.model(**inputs)
                query_embedding = outputs.last_hidden_state.mean(dim=1).cpu().numpy()  # Move back to CPU for numpy operations

            similarities = self._compute_similarity(query_embedding)
            top_k = 5
            top_indices = np.argsort(similarities)[-top_k:][::-1]

            answers = []
            for idx in top_indices:
                if similarities[idx] > 0.5:  # Threshold for relevance
                    answers.append({
                        "документ": self.documents[idx].get("имя_файла", ""),
                        "уверенность": float(similarities[idx]),
                        "ответ": "Данный документ релевантен вашему запросу."
                    })

            logger.info(f"Найдено {len(answers)} ответов")
            return {"ответы": answers}
        except Exception as e:
            logger.error(f"Ошибка при поиске ответа: {str(e)}")
            return {
                "вопрос": question,
                "ответы": [],
                "ошибка": str(e)
            }