from langchain_chroma import Chroma

from sdlc_copilot.config import Settings
from sdlc_copilot.llm.embeddings import build_embeddings
from sdlc_copilot.models import Chunk


def index_chunks(settings: Settings, chunks: list[Chunk], collection_name: str) -> Chroma:
    embeddings = build_embeddings(settings)
    store = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=str(settings.chroma_persist_dir),
    )
    if chunks:
        store.add_texts(
            texts=[chunk.text for chunk in chunks],
            ids=[chunk.id for chunk in chunks],
            metadatas=[chunk.metadata | {"document_id": chunk.document_id, "chunk_index": chunk.index} for chunk in chunks],
        )
    return store
