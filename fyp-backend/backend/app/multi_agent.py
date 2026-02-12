from typing import Dict, Any
from backend.app.llm import get_llm


def _cap(s: str, n: int) -> str:
    s = (s or "").strip()
    return s[:n]


def compute_grade_from_qscores(q_scores: dict) -> int:
    """
    Deterministic grade from q_scores.
    Expects keys: Q1, Q2, Q3 with values 0..3 (ints).
    Total max = 9 => grade out of 100.
    """
    total = 0
    for k in ["Q1", "Q2", "Q3"]:
        try:
            total += int(q_scores.get(k, 0))
        except Exception:
            total += 0
    grade = round((total / 9) * 100)
    return max(0, min(100, grade))


def run_multi_agent(qmap: Dict[int, str], student_context: Dict[str, Any]) -> Dict[str, Any]:
    llm = get_llm()

    # --- Token saver: cap answer text sent to LLM ---
    q1 = _cap(qmap.get(1, ""), 600)
    q2 = _cap(qmap.get(2, ""), 600)
    q3 = _cap(qmap.get(3, ""), 600)

    # Agent 1: correctness (short)
    corr = llm.generate_json(
        system="You are the Correctness Agent. Return STRICT JSON only.",
        user=f"""
Correctness Agent (BE BRIEF)
Student answers:
Q1: {q1}
Q2: {q2}
Q3: {q3}

Return STRICT JSON:
{{
  "q_scores": {{"Q1": 0-3, "Q2": 0-3, "Q3": 0-3}},
  "key_points_found": {{"Q1":[max 3], "Q2":[max 3], "Q3":[max 3]}}
}}
""",
    )

    # ✅ Deterministic grade (no LLM grade drift)
    grade = compute_grade_from_qscores(corr.get("q_scores", {}))

    # Agent 2: misconceptions (very short)
    misc = llm.generate_json(
        system="You are the Misconception Agent. Return STRICT JSON only.",
        user=f"""
Misconception Agent (VERY BRIEF)
For each question return:
- misconceptions: max 1 short sentence
- missing_points_top: max 2 bullet phrases

Student answers:
Q1: {q1}
Q2: {q2}
Q3: {q3}

Return STRICT JSON:
{{
  "Q1": {{"misconceptions":[...], "missing_points_top":[...]}},
  "Q2": {{"misconceptions":[...], "missing_points_top":[...]}},
  "Q3": {{"misconceptions":[...], "missing_points_top":[...]}}
}}
""",
    )

    # Agent 3: clarity (force single object, not list)
    clarity = llm.generate_json(
        system="You are the Clarity Agent. Return STRICT JSON only.",
        user=f"""
Clarity Agent (VERY BRIEF)
Return EXACTLY ONE JSON OBJECT (NOT a list):
{{"clarity_score": 0-10, "writing_suggestions": [max 2 short bullets]}}

Answers:
Q1: {q1}
Q2: {q2}
Q3: {q3}
""",
    )
    if isinstance(clarity, list) and clarity:
        clarity = clarity[0]

    # Agent 4: personalization (minimal context)
    ctx = {
        "weak_concepts": student_context.get("weak_concepts", []),
        "trend": student_context.get("trend", "unknown"),
        "last_feedback_summary": _cap(student_context.get("last_feedback_summary", ""), 200),
    }

    pers = llm.generate_json(
        system="You are the Personalization Agent. Return STRICT JSON only.",
        user=f"""
Personalization Agent (BE BRIEF)
Student context: {ctx}

Return STRICT JSON:
{{
  "personalized_notes": "max 2 sentences",
  "recommended_next_topics": [max 3 topics]
}}

Short answers:
Q1: {_cap(q1, 300)}
Q2: {_cap(q2, 300)}
Q3: {_cap(q3, 300)}
""",
    )

    # Synthesizer (NO grade; we inject grade ourselves)
    synth = llm.generate_json(
        system="You are the Feedback Synthesizer. Return STRICT JSON only.",
        user=f"""
SYNTHESIZER (VERY SHORT OUTPUT)
Do NOT teach. Do NOT write long paragraphs.
Follow limits strictly.

Inputs:
Correctness: {corr}
Misconceptions: {misc}
Clarity: {clarity}
Personalization: {pers}

Return STRICT JSON exactly with these keys:
{{
  "confidence": 0-1,
  "final_feedback": "max 120 words",
  "strengths": [max 3 short bullets],
  "weaknesses": [max 3 short bullets],
  "next_steps": [max 3 short bullets],
  "concept_scores": {{"service":0-1,"clusterip_nodeport":0-1,"networkpolicy":0-1}}
}}
""",
    )

    # Inject deterministic grade
    synth["grade"] = grade

    # QA (check brevity + contradiction vs q_scores)
    qa = llm.generate_json(
        system="You are the Feedback QA Agent. Return STRICT JSON only.",
        user=f"""
Feedback QA Agent
Check:
1) final_feedback <= 120 words
2) strengths/weaknesses/next_steps within limits
3) no contradictions with q_scores:
   - if q_scores are low, feedback must not claim "all perfect"
   - if q_scores are max, feedback should not claim "major mistakes"

Return STRICT JSON:
{{"quality_score":0-1, "issues":[...], "too_long":true/false, "contradiction":true/false}}

q_scores:
{corr.get("q_scores", {})}

Feedback JSON:
{synth}
""",
    )

    # Auto-compress / fix once if needed
    if qa.get("too_long") or qa.get("contradiction"):
        synth2 = llm.generate_json(
            system="You compress and fix feedback. Return STRICT JSON only.",
            user=f"""
COMPRESS & FIX
Rewrite to be shorter and consistent with q_scores.
Rules:
- final_feedback max 80 words
- strengths max 2 bullets
- weaknesses max 2 bullets
- next_steps max 2 bullets
- do NOT change grade (grade is computed)
- keep the same keys

q_scores:
{corr.get("q_scores", {})}

Input JSON:
{synth}

Return STRICT JSON with SAME keys.
""",
        )

        # Ensure grade stays deterministic
        synth2["grade"] = grade

        qa2 = llm.generate_json(
            system="You are the Feedback QA Agent. Return STRICT JSON only.",
            user=f"""
QA AGAIN
Return STRICT JSON:
{{"quality_score":0-1, "issues":[...], "too_long":true/false, "contradiction":true/false}}

q_scores:
{corr.get("q_scores", {})}

Feedback JSON:
{synth2}
""",
        )

        synth = synth2
        qa = qa2

    # Attach agent outputs (store for research/debug)
    synth["agents"] = {
        "correctness": corr,
        "misconceptions": misc,
        "clarity": clarity,
        "personalization": pers,
        "qa": qa,
    }

    return synth
