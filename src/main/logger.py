import logging
import sys
import os
from logging.handlers import TimedRotatingFileHandler

# Configure Log Directory
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Formatters
detailed_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# 1. Info Logger (Everything INFO and above, written to application.log)
# Rotate every 24 hours (midnight), keep 3 days backup
info_handler = TimedRotatingFileHandler(
    f"{LOG_DIR}/application.log", 
    when="midnight", 
    interval=1, 
    backupCount=3,
    encoding='utf-8'
)
info_handler.setLevel(logging.INFO)
info_handler.setFormatter(detailed_formatter)

# 2. Error Logger (Only ERROR and CRITICAL, written to error.log)
# Rotate every 24 hours (midnight), keep 7 days backup
error_handler = TimedRotatingFileHandler(
    f"{LOG_DIR}/error.log", 
    when="midnight", 
    interval=1, 
    backupCount=7,
    encoding='utf-8'
)
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(detailed_formatter)

# 3. Console Handler (Optional: to see logs in Render console / stdout)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(detailed_formatter)

def get_logger(name: str):
    """
    Returns a configured logger instance.
    Usage: logger = get_logger(__name__)
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Avoid adding duplicate handlers if get_logger is called multiple times
    if not logger.handlers:
        logger.addHandler(info_handler)
        logger.addHandler(error_handler)
        logger.addHandler(console_handler)
        
    return logger
