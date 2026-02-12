import json
from typing import Dict, Any, List

def pick_weak_concepts(concept_scores: Dict[str, float], top_k: int = 2) -> List[str]:
    items = sorted(concept_scores.items(), key=lambda x: x[1])
    return [k for k, v in items[:top_k]]

def calc_trend(prev_grade: float | None, new_grade: float) -> str:
    if prev_grade is None:
        return "unknown"
    diff = new_grade - prev_grade
    if diff >= 5:
        return "improving"
    if diff <= -5:
        return "declining"
    return "stable"

def summarize_feedback(text: str, max_len: int = 180) -> str:
    t = (text or "").strip().replace("\n", " ")
    return (t[:max_len] + "...") if len(t) > max_len else t
