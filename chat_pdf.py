import os
import logging
from langchain_community.document_loaders import UnstructuredPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_ollama.chat_models import ChatOllama
from langchain_core.runnables import RunnablePassthrough
from langchain.retrievers.multi_query import MultiQueryRetriever
from typing import List, Dict
from langchain.document_loaders import PyPDFLoader, Docx2txtLoader

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PDFChat:
    def __init__(self, llm_model: str = "bambucha/saiga-llama3", embedding_model: str = "nomic-embed-text", ollama_host: str = "http://localhost:11434"):
        """
        Инициализация чата с PDF
        Args:
            llm_model: модель для генерации ответов
            embedding_model: модель для создания эмбеддингов
            ollama_host: адрес хоста Ollama
        """
        logger.info(f"Initializing PDFChat with Ollama host: {ollama_host}")
        try:
            logger.info("Attempting to connect to Ollama...")
            self.llm = ChatOllama(model=llm_model, base_url=ollama_host)
            self.embeddings = OllamaEmbeddings(
                model=embedding_model,
                base_url=ollama_host
            )
            self.vector_db = None
            self.chat_history = []
            
            # Test connection to Ollama
            logger.info("Testing Ollama connection with embed_query...")
            self.embeddings.embed_query("test")
            logger.info("Successfully connected to Ollama")
        except Exception as e:
            logger.error(f"Failed to connect to Ollama: {str(e)}")
            raise ConnectionError(f"Failed to connect to Ollama at {ollama_host}. Error: {str(e)}")
        
        # Промпт для мульти-запросного ретривера
        self.query_prompt = PromptTemplate(
            input_variables=["question"],
            template="""You are an AI language model assistant. Your task is to generate five
            different versions of the given user question to retrieve relevant documents from
            a vector database. By generating multiple perspectives on the user question, your
            goal is to help the user overcome some of the limitations of the distance-based
            similarity search. Provide these alternative questions separated by newlines.
            Original question: {question}"""
        )
        
        # RAG промпт
        self.rag_prompt = ChatPromptTemplate.from_template(
            """Answer the question based ONLY on the following context and chat history:
            Context: {context}
            Chat History: {chat_history}
            Question: {question}
            """
        )

    def load_pdf(self, pdf_path: str) -> None:
        """
        Загрузка и индексация PDF документа
        Args:
            pdf_path: путь к PDF файлу
        """
        logger.info(f"Loading PDF document from path: {pdf_path}")
        loader = PyPDFLoader(pdf_path)
        self.pages = loader.load_and_split()
        self.db = self._create_vector_db()

    def load_docx(self, docx_path: str) -> None:
        """
        Загрузка и индексация DOCX документа
        Args:
            docx_path: путь к DOCX файлу
        """
        logger.info(f"Loading DOCX document from path: {docx_path}")
        loader = Docx2txtLoader(docx_path)
        self.pages = loader.load_and_split()
        self.db = self._create_vector_db()

    def _create_vector_db(self):
        logger.info("Creating vector database...")
        # Разбиение на чанки
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=7500,
            chunk_overlap=100
        )
        chunks = text_splitter.split_documents(self.pages)
        
        # Создание векторной базы данных
        if self.vector_db:
            self.vector_db.delete_collection()
        
        self.vector_db = Chroma.from_documents(
            documents=chunks,
            embedding=self.embeddings,
            collection_name="pdf-chat"
        )
        
        # Создание ретривера
        self.retriever = MultiQueryRetriever.from_llm(
            self.vector_db.as_retriever(),
            self.llm,
            prompt=self.query_prompt
        )
        
        # Создание RAG цепочки
        self.chain = (
            {
                "context": self.retriever,
                "chat_history": lambda x: str(self.chat_history),
                "question": RunnablePassthrough()
            }
            | self.rag_prompt
            | self.llm
            | StrOutputParser()
        )
        logger.info("Vector database and retriever created successfully")

    def ask(self, question: str) -> str:
        """
        Задать вопрос по загруженному документу
        Args:
            question: вопрос
        Returns:
            ответ на вопрос
        """
        logger.info(f"Asking question: {question}")
        if not self.vector_db:
            raise ValueError("Please load a PDF document first using load_pdf()")
        
        # Получение ответа
        response = self.chain.invoke(question)
        
        # Сохранение в историю чата
        self.chat_history.append({"question": question, "answer": response})
        
        logger.info(f"Received response: {response}")
        return response

    def get_chat_history(self) -> List[Dict]:
        """
        Получить историю чата
        Returns:
            список словарей с вопросами и ответами
        """
        return self.chat_history

    def clear_chat_history(self) -> None:
        """Очистить историю чата"""
        logger.info("Clearing chat history")
        self.chat_history = []

    def get_document_text(self) -> str:
        """
        Получить полный текст загруженного документа
        Returns:
            полный текст документа
        """
        if not self.pages:
            raise ValueError("No document loaded. Please load a document first using load_pdf() or load_docx()")
        
        # Combine all pages into a single text
        full_text = "\n".join([page.page_content for page in self.pages])
        return full_text