# embeddings_wrapper.py
"""
Embedding wrapper supporting two modes:
- BGE API: user provides BGE_API_URL and BGE_API_KEY env vars (POST JSON {"model":"bge-large-en","input":[...]})
- HF fallback: use sentence-transformers (`sentence_transformers`) if available

The script exposes `get_embeddings(list[str]) -> list[list[float]]`.
"""
import os
import json
import requests


class EmbeddingError(Exception):
    pass


class Embedder:
    def __init__(self, mode=None):
        # Determine mode: api if env vars present, else hf if sentence-transformers installed
        self.mode = mode or os.environ.get('EMBED_MODE')
        if not self.mode:
            if os.environ.get('BGE_API_URL') and os.environ.get('BGE_API_KEY'):
                self.mode = 'bge_api'
            else:
                try:
                    import sentence_transformers  # noqa: F401
                    self.mode = 'hf'
                except Exception:
                    self.mode = 'dummy'
        
        if self.mode == 'hf':
            from sentence_transformers import SentenceTransformer
            # default model (small, fast). For production replace with BGE embeddings.
            self.model = SentenceTransformer(os.environ.get('HF_EMBED_MODEL', 'all-MiniLM-L6-v2'))
        elif self.mode == 'bge_api':
            self.api_url = os.environ.get('BGE_API_URL')
            self.api_key = os.environ.get('BGE_API_KEY')
            # optionally model name
            self.model_name = os.environ.get('BGE_MODEL', 'bge-large-en')
        else:
            # dummy uses random vectors (for dry-run)
            import random
            self.random = random

    def get_embeddings(self, texts):
        if self.mode == 'hf':
            return self.model.encode(texts, show_progress_bar=False, convert_to_numpy=True).tolist()
        elif self.mode == 'bge_api':
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f"Bearer {self.api_key}"
            }
            payload = {
                'model': self.model_name,
                'input': texts
            }
            resp = requests.post(self.api_url, headers=headers, data=json.dumps(payload), timeout=60)
            if resp.status_code != 200:
                raise EmbeddingError(f"BGE API failed: {resp.status_code} {resp.text}")
            data = resp.json()
            # expect data['data'][i]['embedding'] or similar
            if 'data' in data and isinstance(data['data'], list):
                embeddings = []
                for item in data['data']:
                    if 'embedding' in item:
                        embeddings.append(item['embedding'])
                    elif 'vector' in item:
                        embeddings.append(item['vector'])
                    else:
                        raise EmbeddingError('Unexpected BGE response format')
                return embeddings
            # fallback if direct field
            if 'embeddings' in data:
                return data['embeddings']
            raise EmbeddingError('Unexpected BGE response format')
        else:
            # dummy
            return [[self.random.random() for _ in range(1536)] for _ in texts]


if __name__ == '__main__':
    e = Embedder()
    print('Mode:', e.mode)
    print('Embedding one example...')
    emb = e.get_embeddings(['hello world'])
    print('Len:', len(emb[0]))
