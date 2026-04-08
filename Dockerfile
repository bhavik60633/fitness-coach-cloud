FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libfreetype6-dev \
    libpng-dev \
    pkg-config \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker cache optimization)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model so it doesn't download at runtime
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application code
COPY . .

# Create dirs
RUN mkdir -p /app/chroma_db /app/obsidian_vault/Conversations

# Build ChromaDB at build time (Railway preserves image layers)
RUN CHROMA_DB_PATH=/app/chroma_db OBSIDIAN_VAULT_PATH=/app/obsidian_vault python ingest.py

# Expose port for health check
EXPOSE 8000

# Start script: re-runs ingest if ChromaDB missing, then starts bot
CMD ["sh", "-c", "python -c \"import chromadb; c=chromadb.PersistentClient('/app/chroma_db'); c.get_collection('fitness_docs')\" 2>/dev/null || CHROMA_DB_PATH=/app/chroma_db python ingest.py; python telegram_bot.py"]
