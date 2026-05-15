#!/usr/bin/env python3
"""
Verify ChromaDB ingestion stats and collection counts.

Usage:
    python verify_ingestion.py
"""

import os
import chromadb

CHROMA_DIR = os.getenv('CHROMA_DB_DIR', '/Users/lalithmachavarapu/Desktop/NLP/chroma_db')
CHROMA_COLLECTION = os.getenv('CHROMA_COLLECTION', 'saarthi_notifications')


def verify_chroma():
    """Verify ChromaDB state and report counts."""
    try:
        # Use PersistentClient to access stored data
        client = chromadb.PersistentClient(path=CHROMA_DIR)
    except Exception as e:
        print(f"Error connecting to ChromaDB: {e}")
        return
    
    # List collections
    collections = client.list_collections()
    print(f"\n{'='*80}")
    print(f"ChromaDB Collections ({len(collections)} total):")
    print(f"{'='*80}\n")
    
    for col in collections:
        print(f"  - {col.name}")
    
    # Get target collection stats
    try:
        collection = client.get_collection(CHROMA_COLLECTION)
        count = collection.count()
        print(f"\n{'='*80}")
        print(f"Collection: {CHROMA_COLLECTION}")
        print(f"{'='*80}")
        print(f"  Total chunks: {count}")
        print(f"  Embedding dimension: {len(collection.get(limit=1)['embeddings'][0]) if collection.get(limit=1)['embeddings'] else 'N/A'}")
        print()
    except Exception as e:
        print(f"Error querying collection {CHROMA_COLLECTION}: {e}")


if __name__ == '__main__':
    verify_chroma()
