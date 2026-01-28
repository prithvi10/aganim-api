from src.main.service.open_ai_api_service import OpenAIService
from src.main.config.configs import EMBEDDING_MODEL


def embed_texts(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    service = OpenAIService()
    return service.embed_texts(texts, model=model or EMBEDDING_MODEL)
