from fastapi import FastAPI
from dotenv import load_dotenv
from contextlib import asynccontextmanager

# 1. Load Environment Variables FIRST
load_dotenv() 

from .controller import router
from src.main.logging.logger import get_logger
from src.main.db.database import engine, Base
from src.main.db import db_models # Import models to ensure they are registered with Base
from scripts.wait_for_db import wait_for_db
from scripts.seed_db import seed_data

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle manager for the FastAPI app.
    Executes startup and shutdown logic.
    """
    try:
        logger.info("🚀 Starting Application Lifecycle...")
        
        # 1. Wait for DB Connection
        logger.info("⏳ Checking database connection...")
        wait_for_db()
        
        # 2. Create Tables (Idempotent)
        # SQLAlchemy's create_all checks for existence first, but let's be explicit in logs.
        # It DOES NOT recreate tables if they exist.
        logger.info("🛠️ Verifying database schema...")
        Base.metadata.create_all(bind=engine)
        
        # 3. Seed Initial Data (Idempotent)
        # The seed_data function checks if records exist before adding them.
        logger.info("🌱 Verifying initial data...")
        seed_data()
        
        logger.info("✅ Application startup complete.")
        yield
    except Exception as e:
        logger.error(f"❌ Application startup failed: {e}")
        raise e
    finally:
        logger.info("🛑 Application shutting down...")

try:
    import truststore
    truststore.inject_into_ssl() # to connect through venv/proxy
    logger.debug("Truststore injection successful")
except ImportError:
    pass # truststore not installed or not needed
except Exception as e:
    logger.debug(f"Truststore injection failed: {e}")

app = FastAPI(lifespan=lifespan)

logger.info("Starting Shopify Translator API...")

# 3. Include the router from controller.py
app.include_router(router)


# To run this: uvicorn main:app --reload
