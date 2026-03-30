"""
ingest.py — Load all PDFs into ChromaDB (works both locally and on cloud).

Run this once locally to build the chroma_db/ folder, then deploy it.

Usage:
    python ingest.py
"""

import os
import hashlib
from pathlib import Path

import fitz  # PyMuPDF
import chromadb
from sentence_transformers import SentenceTransformer

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH      = os.getenv("CHROMA_DB_PATH", "./chroma_db")
COLLECTION   = "fitness_docs"
EMBED_MODEL  = "all-MiniLM-L6-v2"
CHUNK_WORDS  = 400
OVERLAP      = 60
MIN_CHUNK    = 40
# ────────────────────────────────────────────────────────────────────────────


def extract_text(pdf_path: str) -> str:
    """Extract all text from a PDF using PyMuPDF."""
    try:
        doc = fitz.open(pdf_path)
        pages = [page.get_text("text") for page in doc]
        doc.close()
        return "\n".join(pages)
    except Exception as exc:
        print(f"  ⚠  Could not read {pdf_path}: {exc}")
        return ""


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping word-based chunks."""
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunk = " ".join(words[i : i + CHUNK_WORDS])
        if len(chunk.split()) >= MIN_CHUNK:
            chunks.append(chunk)
        i += CHUNK_WORDS - OVERLAP
    return chunks


def chunk_id(pdf_path: str, index: int) -> str:
    raw = f"{pdf_path}::{index}"
    return hashlib.md5(raw.encode()).hexdigest()


def ingest(base_dirs: list[str], db_path: str = DB_PATH) -> None:
    print("\n🏋️  Fitness Coach RAG — PDF Ingestion")
    print("=" * 52)

    # ── ChromaDB
    client = chromadb.PersistentClient(path=db_path)
    try:
        client.delete_collection(COLLECTION)
        print("♻️  Cleared previous database")
    except Exception:
        pass
    collection = client.create_collection(
        COLLECTION, metadata={"hnsw:space": "cosine"}
    )

    # ── Embedding model
    print("⏳  Loading embedding model …")
    embedder = SentenceTransformer(EMBED_MODEL)
    print(f"✅  Embedding model ready ({EMBED_MODEL})")

    # ── Collect PDFs
    all_pdfs: list[Path] = []
    for base in base_dirs:
        p = Path(base)
        if p.exists():
            found = sorted(p.rglob("*.pdf"))
            all_pdfs.extend(found)
            print(f"📂  {p.name}: {len(found)} PDF(s)")
        else:
            print(f"⚠️  Directory not found: {base}")

    if not all_pdfs:
        print("❌  No PDFs found. Check the folder paths.")
        return

    print(f"\n📚  Total PDFs: {len(all_pdfs)}\n")

    # ── Process each PDF
    total_chunks = 0
    BATCH = 64

    for idx, pdf_path in enumerate(all_pdfs, 1):
        print(f"[{idx:02d}/{len(all_pdfs)}] {pdf_path.name}")
        text = extract_text(str(pdf_path))
        if not text.strip():
            print("       ⚠  No extractable text — skipping")
            continue

        chunks = chunk_text(text)
        if not chunks:
            continue

        for start in range(0, len(chunks), BATCH):
            batch_docs  = chunks[start : start + BATCH]
            batch_embs  = embedder.encode(batch_docs, show_progress_bar=False).tolist()
            batch_ids   = [chunk_id(str(pdf_path), start + k) for k in range(len(batch_docs))]
            batch_meta  = [
                {
                    "source": pdf_path.name,
                    "folder": pdf_path.parent.name,
                    "chunk_index": start + k,
                }
                for k in range(len(batch_docs))
            ]
            collection.add(
                embeddings=batch_embs,
                documents=batch_docs,
                ids=batch_ids,
                metadatas=batch_meta,
            )

        total_chunks += len(chunks)
        print(f"       ✓ {len(chunks)} chunks")

    print(f"\n🎉  Done! {total_chunks} chunks stored in {db_path}")


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    script_dir = Path(__file__).parent.resolve()
    parent_dir = script_dir.parent

    dirs = [
        str(parent_dir / "Fitness Coach Details"),
        str(parent_dir / "diet planss"),
    ]
    ingest(dirs)
