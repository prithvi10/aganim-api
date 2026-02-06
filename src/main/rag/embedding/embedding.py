from src.main.services.openai_legacy_service import OpenAIService
from src.main.config.configs import EMBEDDING_MODEL


def embed_texts(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    service = OpenAIService()
    return service.embed_texts(texts, model=model or EMBEDDING_MODEL)
