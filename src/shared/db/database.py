from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from src.shared.config.configs import DATABASE_URL

# For SQLite in tests, allow usage across threads (Starlette TestClient spawns threads)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
