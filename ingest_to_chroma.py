#!/usr/bin/env python3
"""
Ingest PDFs into ChromaDB: chunk -> embed -> store with metadata

Usage (dry-run):
  python ingest_to_chroma.py --dry-run --limit 1

Environment variables (for embeddings):
  - EMBED_MODE: 'bge_api' or 'hf' or 'dummy'
  - BGE_API_URL, BGE_API_KEY (if using bge_api)
  - HF_EMBED_MODEL (optional, default 'all-MiniLM-L6-v2')

"""
import os
import argparse
import glob
import json
import time

from chunker import chunk_text
from embeddings_wrapper import Embedder

try:
    import chromadb
    from chromadb.config import Settings
except Exception:
    chromadb = None

import pdfplumber

SCHEME_DIR = "/Users/lalithmachavarapu/Desktop/NLP/incometax_notifications/pdfs"

COLLECTION_NAME = os.environ.get('CHROMA_COLLECTION', 'saarthi_notifications')
CHROMA_DIR = os.environ.get('CHROMA_DB_DIR', '/Users/lalithmachavarapu/Desktop/NLP/chroma_db')

BATCH_SIZE = 64
TARGET_TOKENS = int(os.environ.get('CHUNK_TOKENS', 400))
OVERLAP_TOKENS = int(os.environ.get('CHUNK_OVERLAP', 50))


def extract_text_from_pdf(path):
    try:
        with pdfplumber.open(path) as pdf:
            texts = []
            for p in pdf.pages:
                t = p.extract_text()
                if t:
                    texts.append(t)
            return "\n".join(texts)
    except Exception as e:
        print('  ✗ PDF read error:', e)
        return ''


def connect_chroma():
    if chromadb is None:
        raise RuntimeError('chromadb not installed')
    # Use PersistentClient for disk persistence
    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        return client
    except AttributeError:
        # Fallback for older chromadb versions
        try:
            client = chromadb.Client(Settings(persist_directory=CHROMA_DIR))
            return client
        except Exception as e:
            raise RuntimeError(f'Could not initialize chromadb client: {e}')


def ingest_files(files, dry_run=False):
    print(f"Processing {len(files)} files (dry_run={dry_run})")
    embedder = Embedder()
    print('Embedder mode:', embedder.mode)

    if not dry_run:
        client = connect_chroma()
        try:
            collection = client.get_collection(COLLECTION_NAME)
        except Exception:
            collection = client.create_collection(COLLECTION_NAME)

    total_chunks = 0
    ids_batch = []
    embs_batch = []
    metas_batch = []
    docs_batch = []

    for idx, pdf_path in enumerate(files):
        if idx and idx % 50 == 0:
            print(f"  processed {idx}/{len(files)} files")

        text = extract_text_from_pdf(pdf_path)
        if not text.strip():
            continue

        # metadata extraction heuristic
        meta = {
            'source_file': os.path.basename(pdf_path),
            'path': pdf_path,
        }

        chunks = list(chunk_text(text, target_tokens=TARGET_TOKENS, overlap_tokens=OVERLAP_TOKENS))
        total_chunks += len(chunks)

        for i, c in enumerate(chunks):
            uid = f"{os.path.basename(pdf_path)}__{i}"
            ids_batch.append(uid)
            docs_batch.append(c)
            metas_batch.append({**meta, 'chunk_index': i})

            if len(ids_batch) >= BATCH_SIZE:
                if dry_run:
                    print(f"  Dry-run: would embed/store {len(ids_batch)} chunks")
                    ids_batch.clear(); embs_batch.clear(); metas_batch.clear(); docs_batch.clear()
                else:
                    embeddings = embedder.get_embeddings(docs_batch)
                    collection.add(ids=ids_batch, embeddings=embeddings, metadatas=metas_batch, documents=docs_batch)
                    ids_batch.clear(); embs_batch.clear(); metas_batch.clear(); docs_batch.clear()

    # final flush
    if ids_batch:
        if dry_run:
            print(f"  Dry-run: would embed/store {len(ids_batch)} chunks (final)")
        else:
            embeddings = embedder.get_embeddings(docs_batch)
            collection.add(ids=ids_batch, embeddings=embeddings, metadatas=metas_batch, documents=docs_batch)

    print('Total chunks prepared:', total_chunks)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int, default=0, help='limit number of files processed')
    parser.add_argument('--sample', action='store_true', help='process small sample (first file)')
    args = parser.parse_args()

    files = sorted(glob.glob(os.path.join(SCHEME_DIR, '*.pdf')))
    if args.limit:
        files = files[:args.limit]
    if args.sample and files:
        files = [files[0]]

    ingest_files(files, dry_run=args.dry_run)
