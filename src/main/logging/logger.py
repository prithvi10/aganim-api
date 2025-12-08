import logging
import sys
import os
from logging.handlers import TimedRotatingFileHandler

# Configure Log Directory
# Allow overriding via environment variable (useful for Render Disks or specific paths)
LOG_DIR = os.getenv("LOG_PATH", "logs")

if not os.path.exists(LOG_DIR):
    try:
        os.makedirs(LOG_DIR)
    except OSError as e:
        # Fallback if we can't create the directory (e.g. permission issues)
        print(f"⚠️ Could not create log directory '{LOG_DIR}': {e}. Logging to files will be disabled.")
        LOG_DIR = None

# Formatters
detailed_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

handlers = []

# 1. Console Handler (CRITICAL for Render)
# Render captures stdout/stderr automatically.
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(detailed_formatter)
handlers.append(console_handler)

# 2. File Handlers (Only if directory exists/was created)
if LOG_DIR:
    # Info Logger (application.log)
    info_handler = TimedRotatingFileHandler(
        f"{LOG_DIR}/application.log", 
        when="midnight", 
        interval=1, 
        backupCount=3,
        encoding='utf-8'
    )
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(detailed_formatter)
    handlers.append(info_handler)

    # Error Logger (error.log)
    error_handler = TimedRotatingFileHandler(
        f"{LOG_DIR}/error.log", 
        when="midnight", 
        interval=1, 
        backupCount=7,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    handlers.append(error_handler)

def get_logger(name: str):
    """
    Returns a configured logger instance.
    Usage: logger = get_logger(__name__)
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Avoid adding duplicate handlers if get_logger is called multiple times
    if not logger.handlers:
        for handler in handlers:
            logger.addHandler(handler)
        
    return logger
