"""
build_index.py — Embed scraped pages and persist FAISS index.
Run once after scraper.py: python build_index.py
Output: faiss_index/index.faiss + faiss_index/chunks.json
"""

import json
import time
from pathlib import Path

import faiss
import numpy as np

from rag_utils import semantic_chunk_text, embed_chunks, build_index


def load_pages(path: str = "knowledge_base/pages.json") -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{path} not found. Run scraper.py first: python scraper.py"
        )
    return json.loads(p.read_text(encoding="utf-8"))


def embed_in_batches(texts: list[str], batch_size: int = 100) -> np.ndarray:
    """Embed in batches to stay within OpenAI per-request limits."""
    all_vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        print(f"  Embedding batch {i // batch_size + 1} / {-(-len(texts) // batch_size)} ({len(batch)} texts)...")
        vecs = embed_chunks(batch)
        all_vecs.append(vecs)
    return np.concatenate(all_vecs, axis=0)


def build_and_save(pages: list[dict], out_dir: str = "faiss_index") -> None:
    Path(out_dir).mkdir(exist_ok=True)

    all_chunks: list[dict] = []
    for page in pages:
        page_chunks = semantic_chunk_text(page["text"], page)
        all_chunks.extend(page_chunks)
        print(f"  {page['title']!r} -> {len(page_chunks)} chunks")

    print(f"\nTotal chunks: {len(all_chunks)}")
    texts = [c["text"] for c in all_chunks]

    print("\nEmbedding chunks via OpenAI...")
    t0 = time.time()
    embeddings = embed_in_batches(texts)
    print(f"Embeddings done in {time.time() - t0:.1f}s")

    index = build_index(embeddings)
    faiss.write_index(index, f"{out_dir}/index.faiss")
    print(f"FAISS index saved -> {out_dir}/index.faiss")

    Path(f"{out_dir}/chunks.json").write_text(
        json.dumps(all_chunks, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Chunk metadata saved -> {out_dir}/chunks.json")


def load_local_docs(kb_dir: str = "knowledge_base") -> list[dict]:
    """Load plain-text .txt files from knowledge_base/ as additional pages."""
    docs = []
    for txt_path in sorted(Path(kb_dir).glob("*.txt")):
        text = txt_path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        # Derive title from first non-empty line
        title = next((ln.strip() for ln in text.splitlines() if ln.strip()), txt_path.stem)
        docs.append({
            "url": "",
            "title": title,
            "text": text,
            "source_file": txt_path.name,
        })
        print(f"  Loaded local doc: {txt_path.name!r} ({len(text)} chars)")
    return docs


def main():
    print("Loading scraped pages...")
    pages = load_pages()
    print(f"{len(pages)} pages loaded\n")

    print("Loading local knowledge base documents...")
    local_docs = load_local_docs()
    print(f"{len(local_docs)} local docs loaded\n")

    all_pages = pages + local_docs
    print(f"Total sources: {len(all_pages)}\n")
    print("Chunking pages...")
    build_and_save(all_pages)
    print("\nIndex build complete.")


if __name__ == "__main__":
    main()
