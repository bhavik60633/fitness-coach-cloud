# -*- coding: utf-8 -*-
"""
ingest.py - Load all PDFs + Obsidian markdown notes into ChromaDB.

Run this once locally to build the chroma_db/ folder, then deploy it.

Usage:
    python ingest.py
"""

import os
import re
import sys
import hashlib
from pathlib import Path

# Force UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


import fitz  # PyMuPDF
import chromadb
from sentence_transformers import SentenceTransformer

# ---- Config -----------------------------------------------------------------
DB_PATH      = os.getenv("CHROMA_DB_PATH", "./chroma_db")
COLLECTION   = "fitness_docs"
EMBED_MODEL  = "all-MiniLM-L6-v2"
CHUNK_WORDS  = 400
OVERLAP      = 60
MIN_CHUNK    = 40

OBSIDIAN_VAULT = os.getenv(
    "OBSIDIAN_VAULT_PATH",
    r"C:\Users\PC\OneDrive\Documents\Obsidian Vault"
)
# -----------------------------------------------------------------------------


def extract_text(pdf_path: str) -> str:
    """Extract all text from a PDF using PyMuPDF."""
    try:
        doc = fitz.open(pdf_path)
        pages = [page.get_text("text") for page in doc]
        doc.close()
        return "\n".join(pages)
    except Exception as exc:
        print(f"  WARN: Could not read {pdf_path}: {exc}")
        return ""


def extract_markdown(md_path: str) -> str:
    """Read an Obsidian markdown file, stripping wikilinks and frontmatter."""
    try:
        text = Path(md_path).read_text(encoding="utf-8")
        # Remove YAML frontmatter
        text = re.sub(r"^---[\s\S]*?---\n", "", text).strip()
        # Convert [[wikilinks]] to plain text
        text = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", text)
        # Remove markdown link syntax, keep text
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        return text
    except Exception as exc:
        print(f"  WARN: Could not read {md_path}: {exc}")
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


def chunk_id(doc_path: str, index: int) -> str:
    raw = f"{doc_path}::{index}"
    return hashlib.md5(raw.encode()).hexdigest()


def ingest_docs(collection, embedder, all_docs: list[tuple[Path, str, str]]) -> int:
    """Embed and store a list of (path, text, doc_type) tuples. Returns total chunks."""
    total_chunks = 0
    BATCH = 64

    for idx, (doc_path, text, doc_type) in enumerate(all_docs, 1):
        print(f"[{idx:02d}/{len(all_docs)}] {doc_path.name}")
        if not text.strip():
            print("       SKIP: no extractable text")
            continue

        chunks = chunk_text(text)
        if not chunks:
            continue

        for start in range(0, len(chunks), BATCH):
            batch_docs = chunks[start : start + BATCH]
            batch_embs = embedder.encode(batch_docs, show_progress_bar=False).tolist()
            batch_ids  = [chunk_id(str(doc_path), start + k) for k in range(len(batch_docs))]
            batch_meta = [
                {
                    "source": doc_path.name,
                    "folder": doc_path.parent.name,
                    "type": doc_type,
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
        print(f"       OK: {len(chunks)} chunks  [{doc_type}]")

    return total_chunks


def ingest(base_dirs: list[str], db_path: str = DB_PATH, obsidian_vault: str = OBSIDIAN_VAULT) -> None:
    print("\nFitness Coach RAG -- Ingestion (PDFs + Obsidian)")
    print("=" * 56)

    client = chromadb.PersistentClient(path=db_path)
    try:
        client.delete_collection(COLLECTION)
        print("Cleared previous database")
    except Exception:
        pass
    collection = client.create_collection(
        COLLECTION, metadata={"hnsw:space": "cosine"}
    )

    print("Loading embedding model ...")
    embedder = SentenceTransformer(EMBED_MODEL)
    print(f"Embedding model ready ({EMBED_MODEL})\n")

    all_docs: list[tuple[Path, str, str]] = []

    # PDFs
    for base in base_dirs:
        p = Path(base)
        if p.exists():
            found = sorted(p.rglob("*.pdf"))
            for pdf in found:
                all_docs.append((pdf, extract_text(str(pdf)), "pdf"))
            print(f"[PDF] {p.name}: {len(found)} PDF(s)")
        else:
            print(f"[WARN] Directory not found: {base}")

    # Obsidian notes
    vault = Path(obsidian_vault)
    if vault.exists():
        md_files = [
            f for f in sorted(vault.rglob("*.md"))
            if ".obsidian" not in str(f)
        ]
        for md in md_files:
            all_docs.append((md, extract_markdown(str(md)), "obsidian_note"))
        print(f"[Notes] Obsidian vault: {len(md_files)} note(s)")
    else:
        print(f"[WARN] Obsidian vault not found: {obsidian_vault}")

    if not all_docs:
        print("No documents found.")
        return

    print(f"\nTotal documents: {len(all_docs)}\n")
    total_chunks = ingest_docs(collection, embedder, all_docs)
    print(f"\nDone! {total_chunks:,} chunks stored in {db_path}")


# ---- Entry point ------------------------------------------------------------
if __name__ == "__main__":
    script_dir = Path(__file__).parent.resolve()
    local_docs  = script_dir / "docs"        # cloud/docs/ — PDFs in repo
    repo_vault  = script_dir / "vault"       # cloud/vault/ — Obsidian notes in repo
    diy_fitness = script_dir.parent.parent   # local dev: DIY fitness/

    if local_docs.exists():
        # Running on Railway/Docker — PDFs in docs/, notes in vault/
        dirs = [
            str(local_docs),
            str(local_docs / "diet planss"),
        ]
        vault = str(repo_vault) if repo_vault.exists() else OBSIDIAN_VAULT
    else:
        # Running locally — PDFs in DIY fitness folder, notes in local Obsidian
        dirs = [
            str(diy_fitness / "Fitness Coach Details"),
            str(diy_fitness / "diet planss"),
        ]
        vault = OBSIDIAN_VAULT

    ingest(dirs, obsidian_vault=vault)
