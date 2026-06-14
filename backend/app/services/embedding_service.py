from typing import Optional

_model = None
MODEL_NAME = "all-MiniLM-L6-v2"


def load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def get_model():
    if _model is None:
        load_model()
    return _model


def embed_text(text: str) -> Optional[list[float]]:
    if not text or not text.strip():
        return None
    try:
        model = get_model()
        embedding = model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    except Exception:
        return None


def embed_batch(texts: list[str]) -> list[Optional[list[float]]]:
    if not texts:
        return []
    try:
        model = get_model()
        embeddings = model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]
    except Exception:
        return [None] * len(texts)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    import numpy as np
    a = np.array(vec_a)
    b = np.array(vec_b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
