import time
import logging
import sys
import os

# Add the project root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.exc import OperationalError
from src.main.db.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def wait_for_db():
    """
    Waits for the database to become available.
    """
    max_retries = 30
    retry_interval = 2

    logger.info("⏳ Waiting for database connection...")
    
    for i in range(max_retries):
        try:
            # Try to connect
            with engine.connect() as connection:
                logger.info("✅ Database connection established!")
                return
        except OperationalError:
            logger.info(f"zzZ Database unavailable, retrying in {retry_interval}s... ({i+1}/{max_retries})")
            time.sleep(retry_interval)
        except Exception as e:
            logger.error(f"❌ Unexpected error connecting to DB: {e}")
            time.sleep(retry_interval)
            
    raise Exception("Could not connect to the database after multiple retries.")

if __name__ == "__main__":
    wait_for_db()

