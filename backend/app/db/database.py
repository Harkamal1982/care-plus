from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings

database_url = URL.create(
    "postgresql+psycopg", username=settings.db_user, password=settings.db_password,
    host=settings.db_host, port=settings.db_port, database=settings.db_name
)
engine = create_engine(database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
class Base(DeclarativeBase):
    pass
def get_db():
    with SessionLocal() as db:
        yield db
