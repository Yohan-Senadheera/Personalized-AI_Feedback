import json
import hashlib
import math
from typing import List
from sentence_transformers import SentenceTransformer

def mock_embedding(text: str, dim: int = 64) -> List[float]:
    """
    Deterministic fake embedding for development.
    Converts text -> a stable numeric vector.
    """
    h = hashlib.sha256(text.encode("utf-8", errors="ignore")).digest()
    nums = list(h)  # 32 bytes
    vec = []
    for i in range(dim):
        b = nums[i % len(nums)]
        # map 0-255 -> -1..1
        v = (b / 127.5) - 1.0
        vec.append(v)
    return vec

def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(y*y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)

def to_json(vec: List[float]) -> str:
    return json.dumps(vec)

def from_json(s: str) -> List[float]:
    return json.loads(s)

_model = None

def local_embedding(text: str) -> list[float]:
    """
    Real semantic embedding (offline/local).
    Uses a small strong model: all-MiniLM-L6-v2
    """
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    vec = _model.encode([text], normalize_embeddings=True)[0]
    return vec.tolist()