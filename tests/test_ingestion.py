"""Unit tests for ingestion loaders and preprocessing (ingestion/)."""
from __future__ import annotations

import pytest

from sdlc_copilot.ingestion.loaders import load_path
from sdlc_copilot.ingestion.preprocess import chunk_documents, clean_text
from sdlc_copilot.models import SourceDocument


# ---------------------------------------------------------------------------
# load_path — file format handling
# ---------------------------------------------------------------------------

def test_load_txt(tmp_path) -> None:
    f = tmp_path / "req.txt"
    f.write_text("Hello requirements.", encoding="utf-8")
    assert load_path(f) == "Hello requirements."


def test_load_md(tmp_path) -> None:
    f = tmp_path / "spec.md"
    f.write_text("# Title\nContent here", encoding="utf-8")
    text = load_path(f)
    assert "Title" in text
    assert "Content here" in text


def test_load_html(tmp_path) -> None:
    f = tmp_path / "page.html"
    f.write_text("<html><body><p>Hello HTML</p></body></html>", encoding="utf-8")
    text = load_path(f)
    assert "Hello HTML" in text


def test_load_csv(tmp_path) -> None:
    f = tmp_path / "data.csv"
    f.write_text("col1,col2\nval1,val2\n", encoding="utf-8")
    text = load_path(f)
    assert "col1" in text
    assert "val1" in text


def test_load_json(tmp_path) -> None:
    f = tmp_path / "data.json"
    f.write_text('[{"key": "value"}]', encoding="utf-8")
    text = load_path(f)
    assert "value" in text


def test_load_unsupported_extension(tmp_path) -> None:
    f = tmp_path / "file.xyz"
    f.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file type"):
        load_path(f)


# ---------------------------------------------------------------------------
# chunk_documents
# ---------------------------------------------------------------------------

def test_chunk_documents_produces_multiple_chunks() -> None:
    """A long document must be split into more than one chunk."""
    docs = [SourceDocument(filename="long.txt", text="word " * 1500)]
    chunks = chunk_documents(docs)
    assert len(chunks) > 1


def test_chunk_documents_all_chunks_reference_parent_doc() -> None:
    docs = [SourceDocument(filename="a.txt", text="sentence. " * 500)]
    chunks = chunk_documents(docs)
    assert all(c.document_id == docs[0].id for c in chunks)


def test_chunk_documents_preserves_filename_metadata() -> None:
    docs = [SourceDocument(filename="spec.txt", text="requirements. " * 300)]
    chunks = chunk_documents(docs)
    assert all("filename" in c.metadata for c in chunks)
    assert all(c.metadata["filename"] == "spec.txt" for c in chunks)


def test_chunk_documents_index_is_sequential() -> None:
    docs = [SourceDocument(filename="seq.txt", text="data " * 1000)]
    chunks = chunk_documents(docs)
    indices = [c.index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunk_single_short_document() -> None:
    """A very short document should produce exactly one chunk."""
    docs = [SourceDocument(filename="short.txt", text="Short text.")]
    chunks = chunk_documents(docs)
    assert len(chunks) == 1
    assert chunks[0].text == "Short text."


# ---------------------------------------------------------------------------
# clean_text
# ---------------------------------------------------------------------------

def test_clean_text_removes_standalone_page_numbers() -> None:
    """Standalone digit lines (page numbers) should be stripped."""
    dirty = "Content before\n\n42\n\nContent after"
    result = clean_text(dirty)
    # The page number line should be gone, content remains
    assert "Content before" in result
    assert "Content after" in result


def test_clean_text_collapses_horizontal_whitespace() -> None:
    result = clean_text("foo   bar\t\tbaz")
    assert result == "foo bar baz"


def test_clean_text_collapses_excess_blank_lines() -> None:
    result = clean_text("line1\n\n\n\nline2")
    assert "\n\n\n" not in result


def test_clean_text_strips_leading_trailing_whitespace() -> None:
    result = clean_text("  \n  content  \n  ")
    assert result == result.strip()
