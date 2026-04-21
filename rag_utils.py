import hashlib
import json
from pathlib import Path

import faiss
import numpy as np
import tiktoken

from config import client, EMBED_MODEL
from file_utils import parse_file

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
MAX_SEMANTIC_TOKENS = 400

# { file_hash: {"chunks": list[dict], "index": faiss.IndexFlatL2} }
embed_cache: dict = {}


def file_hash(path: str) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Fixed-size token chunking. Used as fallback for oversized paragraphs."""
    enc = tiktoken.encoding_for_model(EMBED_MODEL)
    tokens = enc.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = start + chunk_size
        chunks.append(enc.decode(tokens[start:end]))
        if end >= len(tokens):
            break
        start += chunk_size - overlap
    return chunks


def _count_tokens(text: str) -> int:
    enc = tiktoken.encoding_for_model(EMBED_MODEL)
    return len(enc.encode(text))


def _is_section_heading(para: str) -> bool:
    """Heuristic: short paragraph that looks like a section title."""
    stripped = para.strip()
    if not stripped:
        return False
    if len(stripped) > 120:
        return False
    if stripped.endswith(":"):
        return True
    if stripped.isupper() and len(stripped) > 3:
        return True
    return False


def semantic_chunk_text(text: str, page_meta: dict, max_tokens: int = MAX_SEMANTIC_TOKENS) -> list[dict]:
    """
    Paragraph-aware chunking that preserves document structure.
    Returns list[dict] with keys: text, source_url, page_title, section.
    Falls back to fixed-size chunking for oversized single paragraphs.
    """
    source_url = page_meta.get("url", "")
    page_title = page_meta.get("title", "")

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[dict] = []
    buffer: list[str] = []
    buffer_tokens = 0
    current_section = ""

    def flush_buffer():
        if buffer:
            chunks.append({
                "text": "\n\n".join(buffer),
                "source_url": source_url,
                "page_title": page_title,
                "section": current_section,
            })
        buffer.clear()

    for para in paragraphs:
        if _is_section_heading(para):
            flush_buffer()
            buffer_tokens = 0
            current_section = para.strip(": ")

        para_tokens = _count_tokens(para)

        if para_tokens > max_tokens:
            # Flush current buffer first, then split the big paragraph
            flush_buffer()
            buffer_tokens = 0
            for sub in chunk_text(para, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
                chunks.append({
                    "text": sub,
                    "source_url": source_url,
                    "page_title": page_title,
                    "section": current_section,
                })
            continue

        if buffer_tokens + para_tokens > max_tokens:
            flush_buffer()
            buffer_tokens = 0

        buffer.append(para)
        buffer_tokens += para_tokens

    flush_buffer()
    return chunks


def embed_chunks(chunks: list[str]) -> np.ndarray:
    response = client.embeddings.create(model=EMBED_MODEL, input=chunks)
    vectors = [item.embedding for item in response.data]
    return np.array(vectors, dtype=np.float32)


def build_index(embeddings: np.ndarray) -> faiss.IndexFlatL2:
    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)
    return index


def retrieve(query: str, index: faiss.IndexFlatL2, chunks: list, k: int = 4) -> list:
    """
    Returns top-k chunks. Input chunks can be list[str] or list[dict] —
    the return type matches the input type.
    """
    query_vec = embed_chunks([query])
    _, indices = index.search(query_vec, k)
    return [chunks[i] for i in indices[0] if i < len(chunks)]


def load_prebuilt_index(index_dir: str = "faiss_index") -> tuple:
    """
    Load persisted FAISS index and chunk metadata from disk.
    Returns (list[dict], faiss.IndexFlatL2) or (None, None) if not found.
    """
    index_path = Path(index_dir) / "index.faiss"
    chunks_path = Path(index_dir) / "chunks.json"
    if not index_path.exists() or not chunks_path.exists():
        return None, None
    index = faiss.read_index(str(index_path))
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    return chunks, index


def ingest_file(path: str) -> tuple[list[dict], faiss.IndexFlatL2]:
    """Parse, chunk, and embed a user-uploaded file. Returns cached result if unchanged."""
    fh = file_hash(path)
    if fh in embed_cache:
        return embed_cache[fh]["chunks"], embed_cache[fh]["index"]

    try:
        text = parse_file(path)
    except Exception as e:
        raise ValueError(f"Could not parse file: {e}")

    if not text.strip():
        raise ValueError("File contains no readable text.")

    raw_chunks = chunk_text(text)
    chunk_dicts = [
        {
            "text": c,
            "source_url": "",
            "page_title": Path(path).name,
            "section": "",
        }
        for c in raw_chunks
    ]

    texts = [c["text"] for c in chunk_dicts]
    embeddings = embed_chunks(texts)
    index = build_index(embeddings)

    embed_cache[fh] = {"chunks": chunk_dicts, "index": index}
    return chunk_dicts, index
