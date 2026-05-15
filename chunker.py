# chunker.py
"""
Simple clause-level chunker that targets ~400 tokens per chunk (approx by words).
Splits on sentence punctuation then groups sentences to reach token target.
"""
import re

SENT_END_RE = re.compile(r'(?<=[\.!?；;:\n])\s+')


def words_count(text):
    return len(text.split())


def chunk_text(text, target_tokens=400, overlap_tokens=50):
    """Yield chunks of text aiming for target_tokens (approx by words).

    Args:
        text (str): input text
        target_tokens (int): approximate target chunk size in tokens (words)
        overlap_tokens (int): number of words to overlap between adjacent chunks

    Yields:
        str chunks
    """
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return

    # Break into sentence-like pieces
    sentences = SENT_END_RE.split(text)
    sentences = [s.strip() for s in sentences if s.strip()]

    cur_chunk = []
    cur_len = 0

    for sent in sentences:
        sent_len = words_count(sent)
        if cur_len + sent_len <= target_tokens:
            cur_chunk.append(sent)
            cur_len += sent_len
        else:
            if cur_chunk:
                yield " ".join(cur_chunk).strip()
            # start new chunk — if single sentence too long, split by words
            if sent_len > target_tokens:
                words = sent.split()
                i = 0
                while i < len(words):
                    part = words[i:i+target_tokens]
                    yield " ".join(part)
                    i += target_tokens - overlap_tokens
                cur_chunk = []
                cur_len = 0
            else:
                # start with this sentence
                cur_chunk = [sent]
                cur_len = sent_len

    if cur_chunk:
        yield " ".join(cur_chunk).strip()


if __name__ == '__main__':
    # quick self-test
    txt = """This is sentence one. This is sentence two? And the third sentence! """ * 50
    chunks = list(chunk_text(txt, target_tokens=100, overlap_tokens=10))
    print(f"Generated {len(chunks)} chunks")
