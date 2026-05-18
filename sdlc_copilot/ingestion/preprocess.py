import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from sdlc_copilot.models import Chunk, SourceDocument


HEADER_FOOTER_RE = re.compile(r"^\s*(-- \d+ of \d+ --|\d+)\s*$", re.MULTILINE)
WHITESPACE_RE = re.compile(r"[ \t]+")
BLANK_LINES_RE = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    text = HEADER_FOOTER_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text)
    text = BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def chunk_documents(
    documents: list[SourceDocument],
    chunk_size: int = 1800,
    chunk_overlap: int = 250,
) -> list[Chunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks: list[Chunk] = []
    for document in documents:
        for index, text in enumerate(splitter.split_text(clean_text(document.text))):
            chunks.append(
                Chunk(
                    document_id=document.id,
                    text=text,
                    index=index,
                    metadata={"filename": document.filename, **document.metadata},
                )
            )
    return chunks
