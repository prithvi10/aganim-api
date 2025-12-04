from fastapi import FastAPI
from dotenv import load_dotenv
from .controller import router

try:
    import truststore
    truststore.inject_into_ssl() # to connect through venv/proxy
except ImportError:
    pass # truststore not installed or not needed
except Exception as e:
    print(f"Warning: Truststore injection failed: {e}")

# 1. Setup
load_dotenv() # Load your .env file with API keys
app = FastAPI()

# 2. Include the router from controller.py
app.include_router(router)

# To run this: uvicorn main:app --reload
