from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from sdlc_copilot.config import Settings


def build_embeddings(settings: Settings) -> Embeddings:
    if not settings.google_api_key:
        raise ValueError("GOOGLE_API_KEY is required for Google embedding retrieval.")
    # Model id must match Gemini API embedContent (e.g. gemini-embedding-001). Legacy
    # models/text-embedding-004 often returns NOT_FOUND with the current google-genai client.
    return GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=settings.google_api_key,
    )
