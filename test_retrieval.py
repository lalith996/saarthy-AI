#!/usr/bin/env python3
"""
Test retrieval and QA from ChromaDB.

Usage:
    python test_retrieval.py "What is PMJAY?"
    python test_retrieval.py "Eligibility for APY"
"""

import sys
import os
import chromadb
from embeddings_wrapper import Embedder

CHROMA_DIR = os.getenv('CHROMA_DB_DIR', '/Users/lalithmachavarapu/Desktop/NLP/chroma_db')
CHROMA_COLLECTION = os.getenv('CHROMA_COLLECTION', 'saarthi_notifications')


def get_chroma_client():
    """Connect to ChromaDB."""
    try:
        # Use PersistentClient to access stored data
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        return client
    except Exception as e:
        raise RuntimeError(f'Could not initialize chromadb client: {e}')


def retrieve_chunks(query: str, k: int = 5):
    """Retrieve top-k chunks matching query."""
    client = get_chroma_client()
    embedder = Embedder()
    
    # Embed query
    query_embed = embedder.get_embeddings([query])[0]
    
    # Query collection
    collection = client.get_collection(CHROMA_COLLECTION)
    results = collection.query(query_embeddings=[query_embed], n_results=k)
    
    return results


def format_retrieval_result(results):
    """Pretty-print retrieval results."""
    if not results or not results.get('documents'):
        print("No results found.")
        return
    
    docs = results['documents'][0]
    metadatas = results['metadatas'][0] if results.get('metadatas') else []
    distances = results['distances'][0] if results.get('distances') else []
    
    print(f"\n{'='*80}")
    print(f"Retrieved {len(docs)} chunk(s):")
    print(f"{'='*80}\n")
    
    for i, (doc, meta, dist) in enumerate(zip(docs, metadatas, distances), 1):
        print(f"[{i}] Distance: {dist:.4f}")
        if meta:
            print(f"    Source: {meta.get('source_file', 'unknown')}")
            if meta.get('title'):
                print(f"    Title: {meta.get('title')}")
        print(f"    Content: {doc[:200]}...")
        print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_retrieval.py '<query>'")
        print("Example: python test_retrieval.py 'What is PMJAY?'")
        sys.exit(1)
    
    query = ' '.join(sys.argv[1:])
    print(f"Query: {query}")
    
    results = retrieve_chunks(query, k=5)
    format_retrieval_result(results)


if __name__ == '__main__':
    main()
