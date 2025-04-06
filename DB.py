from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy import Column, BigInteger, String, ForeignKey, select
from typing import Union, List, Optional
import asyncio
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создание БД и подключение
DATABASE_URL = 'postgresql+asyncpg://postgres:1234qwerttest@45.81.243.111:5432/postgres'
engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine)

# Base - основной класс, с помощью него происходит управление всеми остальными классами (таблицами)
class Base(AsyncAttrs, DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    users_name = Column(String, nullable=False)  # Имя пользователя
    users_id = Column(BigInteger, unique=True, nullable=False)  # Telegram ID пользователя

    # Связь с историей - один пользователь имеет много записей истории
    history = relationship("History", back_populates="user")

class History(Base):
    __tablename__ = 'history'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id_users = Column(BigInteger, ForeignKey('users.users_id', ondelete='CASCADE'), nullable=False)  # Связь с таблицей users
    path_to_tz = Column(String, nullable=False)  # Путь к файлу ТЗ
    path_to_analyze = Column(String, nullable=False)  # Путь к файлу анализа

    # Связь с пользователем - каждая запись истории принадлежит одному пользователю
    user = relationship("User", back_populates="history")

# Функция, которая создаёт таблицы только если их не существует
async def create_tables():
    async with engine.begin() as conn:
        # Проверяем существуют ли таблицы
        try:
            # Вместо удаления таблиц, просто создаем их, если они не существуют
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Таблицы проверены/созданы")
        except Exception as e:
            logger.error(f"Ошибка при создании таблиц: {e}")

# ИСПРАВЛЕННЫЕ CRUD операции - убраны await session.commit()

# CRUD операции для User
async def create_user(session, users_name: str, users_id: int) -> User:
    """Создание нового пользователя"""
    try:
        new_user = User(users_name=users_name, users_id=users_id)
        session.add(new_user)
        # Комментируем await session.commit() - управление транзакциями теперь через контекст
        return new_user
    except Exception as e:
        logger.error(f"Ошибка при создании пользователя: {e}")
        raise

async def get_user_by_telegram_id(session, users_id: int) -> Optional[User]:
    """Получение пользователя по Telegram ID"""
    query = select(User).where(User.users_id == users_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()

async def update_user(session, users_id: int, **kwargs) -> Optional[User]:
    """Обновление данных пользователя"""
    try:
        user = await get_user_by_telegram_id(session, users_id)
        if user:
            for key, value in kwargs.items():
                setattr(user, key, value)
        return user
    except Exception as e:
        logger.error(f"Ошибка при обновлении пользователя: {e}")
        raise

async def delete_user(session, users_id: int) -> bool:
    """Удаление пользователя"""
    try:
        user = await get_user_by_telegram_id(session, users_id)
        if user:
            await session.delete(user)
            # Комментируем await session.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Ошибка при удалении пользователя: {e}")
        raise

# CRUD операции для History
async def create_history(
    session, 
    users_id: int, 
    path_to_tz: str, 
    path_to_analyze: str
) -> History:
    """Создание новой записи в истории"""
    try:
        new_history = History(
            telegram_id_users=users_id,
            path_to_tz=path_to_tz,
            path_to_analyze=path_to_analyze
        )
        session.add(new_history)
        # Комментируем await session.commit()
        return new_history
    except Exception as e:
        logger.error(f"Ошибка при создании записи истории: {e}")
        raise

async def get_history_by_id(session, history_id: int) -> Optional[History]:
    """Получение записи истории по id"""
    query = select(History).where(History.id == history_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()

async def get_user_history(session, users_id: int) -> List[History]:
    """Получение всей истории пользователя"""
    query = select(History).where(History.telegram_id_users == users_id)
    result = await session.execute(query)
    return list(result.scalars().all())

async def delete_history(session, history_id: int) -> bool:
    """Удаление записи истории"""
    try:
        history = await get_history_by_id(session, history_id)
        if history:
            await session.delete(history)
            # Комментируем await session.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Ошибка при удалении записи истории: {e}")
        raise

# Тестирование соединения отдельно
async def test_db_connection():
    try:
        async with engine.connect() as conn:
            await conn.execute(select(1))
            logger.info("Подключение к БД успешно")
            return True
    except Exception as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        return False

# Основная асинхронная функция для тестирования
async def async_main():
    # Сначала проверяем подключение
    connection_ok = await test_db_connection()
    if not connection_ok:
        logger.error("Невозможно продолжить без подключения к БД")
        return
    
    # Создаем таблицы
    await create_tables()
    
    # Тестируем CRUD операции
    async with async_session() as session:
        async with session.begin():
            try:
                # Создаем пользователя
                user = await create_user(session, "Test User", 123456789)
                logger.info(f"Создан пользователь: {user.users_name} (ID: {user.users_id})")
                
                # Создаем запись в истории
                history = await create_history(
                    session,
                    user.users_id,
                    "/path/to/tz.pdf",
                    "/path/to/analysis.pdf"
                )
                logger.info(f"Создана запись в истории для пользователя {user.users_id}")
                
                # Получаем историю пользователя
                user_history = await get_user_history(session, user.users_id)
                logger.info(f"Найдено записей в истории: {len(user_history)}")
            except Exception as e:
                logger.error(f"Ошибка при тестировании CRUD: {e}")

if __name__ == "__main__":
    asyncio.run(async_main())