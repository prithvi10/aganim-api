from fastapi import FastAPI
from dotenv import load_dotenv

# 1. Load Environment Variables FIRST
load_dotenv() 

from .controller import router
from .logger import get_logger
from .database import engine, Base
from . import db_models # Import models to ensure they are registered with Base

logger = get_logger(__name__)

# 2. Create Database Tables
Base.metadata.create_all(bind=engine)

try:
    import truststore
    truststore.inject_into_ssl() # to connect through venv/proxy
    logger.debug("Truststore injection successful")
except ImportError:
    pass # truststore not installed or not needed
except Exception as e:
    logger.debug(f"Truststore injection failed: {e}")

app = FastAPI()

logger.info("Starting Shopify Translator API...")

# 3. Include the router from controller.py
app.include_router(router)

# To run this: uvicorn main:app --reload
