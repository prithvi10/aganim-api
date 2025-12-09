from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
import uvicorn
from contextlib import asynccontextmanager

from src.main.config.configs import DATABASE_URL
from src.main.db.database import engine, Base, get_db
from src.main.api.controller import router as api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown: (Cleanup if needed)

app = FastAPI(lifespan=lifespan)

# Include the API router
app.include_router(api_router)

# Health Check Endpoint
@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint for cloud providers.
    Checks:
    1. App is running (returns 200)
    2. Database connection is active
    """
    try:
        # Simple query to verify DB connection
        db.execute(text("SELECT 1"))
        return JSONResponse(status_code=200, content={"status": "healthy", "database": "connected"})
    except Exception as e:
        return JSONResponse(
            status_code=503, 
            content={"status": "unhealthy", "database": "disconnected", "error": str(e)}
        )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
