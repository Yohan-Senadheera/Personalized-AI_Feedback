from typing import Dict, Any, List
from backend.app.llm import get_llm
import re
import json

print("LOADED LIVE multi_agent.py")


def _cap(s: str, n: int) -> str:
    return (s or "").strip()[:n]


def _norm(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("traƯic", "traffic")
    s = s.replace("\r", "\n")
    return s


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s+\n", "\n\n", s)
    return s.strip()


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default

def _safe_score(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v, default=0):
    try:
        return int(round(float(v)))
    except Exception:
        return default


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _avg(values: List[float]):
    vals = [x for x in values if isinstance(x, (int, float))]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def _tokenize_words(s: str) -> List[str]:
    s = _norm(s).lower()
    return re.findall(r"[a-zA-Z][a-zA-Z0-9_\-]{2,}", s)


def _extract_questions_from_prompt(prompt: str) -> List[dict]:
    text = _strip_html(_norm(prompt))
    lines = [x.strip() for x in text.splitlines() if x.strip()]

    questions = []
    for line in lines:
        m = re.match(r"^(\d+)[\.\)]\s*(.+)$", line)
        if m:
            qno = int(m.group(1))
            qtext = m.group(2).strip()
            questions.append({"qno": qno, "question": qtext})

    return questions


def _concepts_from_question_text(question: str, qno: int) -> List[str]:
    q = _norm(question).lower()

    manual = []
    keyword_map = {
        "docker image": "docker_image",
        "image": "docker_image",
        "docker container": "docker_container",
        "container": "docker_container",
        "docker compose": "docker_compose",
        "compose": "docker_compose",
        "containerization": "containerization",
        "kubernetes service": "kubernetes_service",
        "service": "service_concept",
        "clusterip": "clusterip",
        "nodeport": "nodeport",
        "networkpolicy": "networkpolicy",
        "network policy": "networkpolicy",
        "ingress": "ingress",
        "loadbalancer": "loadbalancer",
        "pod": "pod_networking",
    }

    for k, v in keyword_map.items():
        if k in q and v not in manual:
            manual.append(v)

    if not manual:
        words = _tokenize_words(question)
        manual = words[:2] if words else [f"q{qno}_understanding"]

    return manual[:4]


def _fallback_rubric(question_defs: List[dict], qmap: Dict[int, str], default_max_score: int = 3) -> List[dict]:
    out = []
    seen = set()

    for q in question_defs:
        qno = _safe_int(q.get("qno"), 0)
        if qno <= 0:
            continue
        question = (q.get("question") or f"Question {qno}").strip()
        out.append({
            "qno": qno,
            "question": question,
            "max_score": default_max_score,
            "criteria": [
                "Correct core idea",
                "Relevant technical detail",
                "Clear explanation or example",
            ],
            "concepts": _concepts_from_question_text(question, qno),
        })
        seen.add(qno)

    for qno in sorted(qmap.keys()):
        if qno not in seen:
            out.append({
                "qno": qno,
                "question": f"Question {qno}",
                "max_score": default_max_score,
                "criteria": [
                    "Correct core idea",
                    "Relevant technical detail",
                    "Clear explanation or example",
                ],
                "concepts": [f"q{qno}_understanding"],
            })

    out.sort(key=lambda x: x["qno"])
    return out


def _normalize_rubric(rubric_questions: List[dict], fallback_questions: List[dict]) -> List[dict]:
    fallback_by_qno = {x["qno"]: x for x in fallback_questions}
    out = []

    for item in rubric_questions or []:
        qno = _safe_int(item.get("qno"), 0)
        if qno <= 0 or qno not in fallback_by_qno:
            continue

        fb = fallback_by_qno[qno]
        max_score = _clamp(_safe_int(item.get("max_score", fb["max_score"]), fb["max_score"]), 1, 10)
        question = (item.get("question") or fb["question"]).strip()
        criteria = [str(x).strip() for x in (item.get("criteria") or []) if str(x).strip()][:6]
        concepts = [str(x).strip() for x in (item.get("concepts") or []) if str(x).strip()][:6]

        if len(criteria) < 2:
            criteria = fb["criteria"]
        if not concepts:
            concepts = fb["concepts"]

        out.append({
            "qno": qno,
            "question": question,
            "max_score": max_score,
            "criteria": criteria,
            "concepts": concepts,
        })

    seen = {x["qno"] for x in out}
    for fb in fallback_questions:
        if fb["qno"] not in seen:
            out.append(fb)

    out.sort(key=lambda x: x["qno"])
    return out


def _normalize_eval(eval_json: dict, rubric_questions: List[dict]) -> dict:
    per_question = eval_json.get("per_question", {}) if isinstance(eval_json, dict) else {}
    out = {}

    for rq in rubric_questions:
        qno = rq["qno"]
        key = f"Q{qno}"
        item = per_question.get(key, {}) if isinstance(per_question, dict) else {}

        max_score = float(_clamp(_safe_float(item.get("max_score", rq["max_score"]), rq["max_score"]), 1, 10))
        score = round(_clamp(_safe_float(item.get("score", 0), 0.0), 0.0, max_score), 2)


        reason = (item.get("reason") or "").strip()
        strengths = [str(x).strip() for x in (item.get("strengths") or []) if str(x).strip()][:3]
        gaps = [str(x).strip() for x in (item.get("gaps") or []) if str(x).strip()][:3]
        concepts = [str(x).strip() for x in (item.get("concepts") or rq.get("concepts") or []) if str(x).strip()][:6]

        out[key] = {
            "score": score,
            "max_score": max_score,
            "reason": reason,
            "strengths": strengths,
            "gaps": gaps,
            "concepts": concepts,
        }

    overall_strengths = [str(x).strip() for x in (eval_json.get("overall_strengths") or []) if str(x).strip()][:4]
    overall_weaknesses = [str(x).strip() for x in (eval_json.get("overall_weaknesses") or []) if str(x).strip()][:4]
    next_steps = [str(x).strip() for x in (eval_json.get("next_steps") or []) if str(x).strip()][:4]

    concept_scores = eval_json.get("concept_scores") or {}
    concept_scores_norm = {}
    if isinstance(concept_scores, dict):
        for k, v in concept_scores.items():
            kk = str(k).strip()
            if kk:
                concept_scores_norm[kk] = round(_clamp(_safe_float(v, 0.0), 0.0, 1.0), 2)

    confidence = round(_clamp(_safe_float(eval_json.get("confidence", 0.55), 0.55), 0.0, 1.0), 2)

    return {
        "per_question": out,
        "overall_strengths": overall_strengths,
        "overall_weaknesses": overall_weaknesses,
        "next_steps": next_steps,
        "concept_scores": concept_scores_norm,
        "confidence": confidence,
    }


def _derive_concept_scores(per_question: dict) -> dict:
    bucket = {}
    for _, item in per_question.items():
        max_score = max(1, item["max_score"])
        ratio = round(item["score"] / max_score, 2)
        for c in item.get("concepts", []):
            bucket.setdefault(c, []).append(ratio)

    return {k: round(sum(v) / len(v), 2) for k, v in bucket.items() if v}


def _compute_grade(
    per_question: dict,
    dataset_name: str = "",
    dataset_grade_max: float | None = None
) -> float:
    total = 0.0
    total_max = 0.0

    for _, item in per_question.items():
        total += float(item["score"])
        total_max += float(item["max_score"])

    if total_max <= 0:
        return 0.0

    ratio = total / total_max

    if dataset_name.upper() == "ASAG":
        if ratio <= 0.25:
            return 0.0
        if ratio < 0.75:
            return 50.0
        return 100.0

    if dataset_grade_max is not None and dataset_grade_max > 0:
        return round(ratio * float(dataset_grade_max), 2)

    return round(ratio * 100.0, 2)



def _filter_personalization_to_assignment(student_context: Dict[str, Any], rubric_questions: List[dict]) -> Dict[str, Any]:
    active_concepts = set()
    for rq in rubric_questions:
        for c in rq.get("concepts", []) or []:
            if c:
                active_concepts.add(c)

    raw_weak = student_context.get("weak_concepts", []) or []
    filtered_weak = [c for c in raw_weak if c in active_concepts]

    recent_concepts = student_context.get("recent_concepts", []) or []
    filtered_recent = []
    for row in recent_concepts:
        if isinstance(row, dict):
            filtered_recent.append({
                k: v for k, v in row.items()
                if k in active_concepts and isinstance(v, (int, float))
            })

    return {
        **student_context,
        "weak_concepts": filtered_weak,
        "recent_concepts": filtered_recent,
    }


def _build_personalization_context(student_context: Dict[str, Any]) -> Dict[str, Any]:
    recent_concepts = student_context.get("recent_concepts", []) or []

    concept_names = set()
    for row in recent_concepts:
        if isinstance(row, dict):
            concept_names.update(row.keys())

    recent_concepts_avg = {}
    for c in concept_names:
        vals = []
        for row in recent_concepts:
            if isinstance(row, dict):
                v = row.get(c)
                if isinstance(v, (int, float)):
                    vals.append(float(v))
        avg = _avg(vals)
        if avg is not None:
            recent_concepts_avg[c] = avg

    return {
        "weak_concepts": student_context.get("weak_concepts", []) or [],
        "trend": student_context.get("trend", "unknown"),
        "recent_grades": (student_context.get("recent_grades", []) or [])[-3:],
        "recent_feedback_summaries": (student_context.get("recent_feedback_summaries", []) or [])[-2:],
        "recent_concepts_avg": recent_concepts_avg,
        "plagiarism_flag": bool(student_context.get("plagiarism_flag", False)),
    }


def _fallback_reason(score: int, max_score: int, question: str) -> str:
    if score >= max_score:
        return f"Strong answer for: {question}"
    if score == 0:
        return f"Answer is incorrect, missing, or not aligned with the question: {question}"
    return f"Partially correct answer for: {question}"


def _heuristic_score_answer(question: str, answer: str, max_score: float) -> float:
    q_words = set(_tokenize_words(question))
    a_words = set(_tokenize_words(answer))
    overlap = len(q_words.intersection(a_words))
    answer_len = len(a_words)

    if answer_len == 0:
        return 0.0
    if overlap >= 4 and answer_len >= 12:
        return float(max_score)
    if overlap >= 2 and answer_len >= 8:
        return round(float(max_score) * 0.5, 2)
    if answer_len >= 6:
        return round(float(max_score) * 0.25, 2)
    return 0.0



def _fallback_evaluate_answers(rubric_questions: List[dict], qmap: Dict[int, str]) -> dict:
    per_question = {}
    overall_strengths = []
    overall_weaknesses = []
    next_steps = []

    for rq in rubric_questions:
        qno = rq["qno"]
        key = f"Q{qno}"
        answer = _norm(qmap.get(qno, ""))
        question = rq["question"]
        concepts = rq.get("concepts", [])
        max_score = rq["max_score"]

        score = _heuristic_score_answer(question, answer, max_score)
        reason = _fallback_reason(score, max_score, question)

        strengths = []
        gaps = []

        if score == max_score:
            strengths.append(f"You addressed {key} well.")
            overall_strengths.append(f"{key} was strong.")
        elif score == 0:
            gaps.append(f"{key} needs a more accurate answer.")
            overall_weaknesses.append(f"{key} was incorrect or too weak.")
            next_steps.append(f"Review the expected technical points for {key} and answer with more precision.")
        else:
            strengths.append(f"{key} is partly correct.")
            gaps.append(f"{key} needs more technical detail.")
            overall_weaknesses.append(f"{key} needs more depth.")
            next_steps.append(f"Review the expected technical points for {key} and answer with more precision.")

        per_question[key] = {
            "score": score,
            "max_score": max_score,
            "reason": reason,
            "strengths": strengths[:3],
            "gaps": gaps[:3],
            "concepts": concepts[:6],
        }

    concept_scores = _derive_concept_scores(per_question)

    return {
        "per_question": per_question,
        "overall_strengths": overall_strengths[:4],
        "overall_weaknesses": overall_weaknesses[:4],
        "next_steps": next_steps[:4],
        "concept_scores": concept_scores,
        "confidence": 0.35,
    }


def _needs_eval_fallback(evaluation: dict) -> bool:
    per_question = evaluation.get("per_question", {})
    if not per_question:
        return True

    total_questions = 0
    nonempty_reason = 0
    for _, item in per_question.items():
        total_questions += 1
        if item.get("reason"):
            nonempty_reason += 1

    if total_questions == 0:
        return True
    if nonempty_reason == 0:
        return True
    return False


def _looks_suspicious(evaluation: dict, answers_payload: List[dict]) -> bool:
    perq = evaluation.get("per_question", {})
    if not perq:
        return True

    for ans in answers_payload:
        key = f"Q{ans['qno']}"
        item = perq.get(key, {})
        answer = (ans.get("answer") or "").strip()
        score = int(item.get("score", 0))
        max_score = max(1, int(item.get("max_score", 1)))
        reason = (item.get("reason") or "").strip().lower()

        # suspicious if answer is empty but got marks
        if not answer and score > 0:
            return True

        # suspicious if full marks but no reason
        if score == max_score and not reason:
            return True

        # suspicious if zero marks but reason says partly correct / correct
        if score == 0 and any(x in reason for x in ["partly correct", "partially correct", "some correct", "mostly correct", "correct"]):
            return True

    return False



def _feedback_looks_generic(text: str, assignment_title: str, assignment_prompt: str = "") -> bool:
    t = _norm(text).lower()
    if not t:
        return True

    assignment_text = f"{assignment_title} {assignment_prompt}".lower()
    is_k8s = any(x in assignment_text for x in [
        "kubernetes", "clusterip", "nodeport", "networkpolicy", "ingress", "loadbalancer", "service"
    ])

    bad_patterns = ["good work overall"]

    if not is_k8s:
        bad_patterns.extend([
            "label-selector",
            "ingress/loadbalancer",
            "clusterip",
            "nodeport",
            "networkpolicy",
        ])

    return any(x in t for x in bad_patterns)


def _build_fallback_feedback(
    assignment_title: str,
    evaluation: dict,
    personalization_context: dict,
    grade: int,
) -> dict:
    per_question = evaluation["per_question"]

    parts = [f"Your score for {assignment_title} is {grade}."]
    strengths = []
    weaknesses = []
    next_steps = []

    for key in sorted(per_question.keys()):
        item = per_question[key]
        parts.append(f"{key}: {item['reason']}")
        strengths.extend(item.get("strengths", []))
        weaknesses.extend(item.get("gaps", []))

    trend = personalization_context.get("trend", "unknown")
    weak_concepts = personalization_context.get("weak_concepts", []) or []

    if trend != "unknown":
        parts.append(f"Your recent trend is {trend}.")
    if weak_concepts:
        parts.append("Focus especially on: " + ", ".join(weak_concepts[:3]) + ".")

    for key in sorted(per_question.keys()):
        item = per_question[key]
        if item["score"] < item["max_score"]:
            next_steps.append(f"Review the expected technical points for {key} and answer with more precision.")

    return {
        "final_feedback": " ".join(parts),
        "strengths": strengths[:3],
        "weaknesses": weaknesses[:3],
        "next_steps": next_steps[:3],
        "confidence": 0.55,
    }


def run_multi_agent(
    qmap: Dict[int, str],
    student_context: Dict[str, Any],
    assignment_context: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    llm = get_llm()
    print("RUNNING LIVE run_multi_agent")

    assignment_context = assignment_context or {}
    assignment_title = (assignment_context.get("assignment_title") or "Assignment").strip()
    assignment_prompt = _strip_html(assignment_context.get("assignment_prompt") or "")
    reference_answer = _strip_html(assignment_context.get("reference_answer") or "")
    dataset_name = (assignment_context.get("dataset_name") or "").strip()
    dataset_max_score = _safe_int(assignment_context.get("dataset_max_score"), 3)
    if dataset_max_score <= 0:
        dataset_max_score = 3

    question_defs = _extract_questions_from_prompt(assignment_prompt)
    if not question_defs:
        question_defs = [{"qno": qno, "question": f"Question {qno}"} for qno in sorted(qmap.keys())]

    fallback_rubric = _fallback_rubric(question_defs, qmap, default_max_score=dataset_max_score)

    answers_payload = []
    for q in fallback_rubric:
        qno = q["qno"]
        answers_payload.append({
            "qno": qno,
            "question": q["question"],
            "answer": _cap(_norm(qmap.get(qno, "")), 2000),
        })

    rubric_json = llm.generate_json(
        system="You are the Rubric Interpreter Agent. Return STRICT JSON only.",
        user=f"""
Assignment title:
{assignment_title}

Assignment prompt:
{assignment_prompt}

Reference answer:
{reference_answer}

Detected questions:
{json.dumps(question_defs, ensure_ascii=False)}

Create a grading rubric for each question.

Rules:
- If dataset_max_score is provided, use that as max_score for each question unless the assignment explicitly gives another score.
- dataset_max_score for this run is {dataset_max_score}.
- For each question, write 3 to 5 concrete expected points.
- Criteria must be specific to the actual question, not generic.
- Concepts must be assignment-topic concepts only.
- Do not mention Kubernetes unless the assignment is about Kubernetes.
- Do not mention Docker unless the assignment is about Docker.
- Return one entry for every detected question.

Return STRICT JSON:
{{
  "questions": [
    {{
      "qno": 1,
      "question": "text",
      "max_score": {dataset_max_score},
      "criteria": [
        "specific expected point 1",
        "specific expected point 2",
        "specific expected point 3"
      ],
      "concepts": ["concept_a", "concept_b"]
    }}
  ]
}}
"""
    )

    rubric_questions = _normalize_rubric(rubric_json.get("questions", []), fallback_rubric)

    student_context = _filter_personalization_to_assignment(student_context, rubric_questions)
    personalization_context = _build_personalization_context(student_context)

    eval_json = llm.generate_json(
        system="You are a strict but fair academic short-answer grader. Grade for meaning, not wording. Return STRICT JSON only.",
        user=f"""
Grade the student's answers using the rubric and reference answer.

Assignment title:
{assignment_title}

Assignment prompt:
{assignment_prompt}

Reference answer:
{reference_answer}

Rubric:
{json.dumps(rubric_questions, ensure_ascii=False)}

Student answers:
{json.dumps(answers_payload, ensure_ascii=False)}

Return STRICT JSON:
{{
  "per_question": {{
    "Q1": {{
      "score": 0,
      "max_score": {dataset_max_score},
      "reason": "one or two sentences",
      "strengths": ["..."],
      "gaps": ["..."],
      "concepts": ["..."]
    }}
  }},
  "overall_strengths": ["..."],
  "overall_weaknesses": ["..."],
  "next_steps": ["..."],
  "concept_scores": {{
    "concept_name": 0.0
  }},
  "confidence": 0.0
}}

Rules:
- score must be between 0 and max_score
- For VALIDATION_FEEDBACK, scores may use 0.5-step partial credit.
- compare the student's meaning against the reference answer and rubric
- accept paraphrases, brief answers, and minor grammar mistakes when the meaning is correct
- for ASAG-style short answers, do not require exact wording
- award full credit when the core idea is correct and sufficient
- award partial credit when the answer is partly correct but incomplete
- give zero only when the answer is wrong, reversed, off-topic, or missing the main idea
- reason must mention why marks were awarded or lost
- feedback must match actual answer quality
- do not use markdown
"""
    )
    print("DEBUG rubric_json:", json.dumps(rubric_json, indent=2, ensure_ascii=False))
    print("DEBUG eval_json:", json.dumps(eval_json, indent=2, ensure_ascii=False))
    evaluation = _normalize_eval(eval_json, rubric_questions)

    if _needs_eval_fallback(evaluation) or _looks_suspicious(evaluation, answers_payload):
        print("⚠️ Falling back to heuristic evaluation")
        evaluation = _fallback_evaluate_answers(rubric_questions, qmap)

    if not evaluation["concept_scores"]:
        evaluation["concept_scores"] = _derive_concept_scores(evaluation["per_question"])

    grade = _compute_grade(
    evaluation["per_question"],
    dataset_name=dataset_name,
    dataset_grade_max=assignment_context.get("dataset_grade_max"),
)


    feedback_json = llm.generate_json(
        system="You are the Personalized Feedback Agent. Return STRICT JSON only.",
        user=f"""
Create personalized feedback using the grading result and student history.

Assignment title:
{assignment_title}

Evaluation:
{json.dumps(evaluation, ensure_ascii=False)}

Student history:
{json.dumps(personalization_context, ensure_ascii=False)}

Return STRICT JSON:
{{
  "final_feedback": "120-220 words, specific and not generic",
  "strengths": ["...", "..."],
  "weaknesses": ["...", "..."],
  "next_steps": ["...", "..."],
  "confidence": 0.0
}}

Rules:
- Mention the actual assignment topic
- Do not mention Kubernetes unless this assignment is Kubernetes
- Do not mention ClusterIP, NodePort, NetworkPolicy unless this assignment is Kubernetes
- Do not mention label-selector, Ingress, or LoadBalancer unless relevant
- Do not invent mistakes not present in evaluation
- If a question is weak, mention that question specifically
- Use the student history only when relevant
- Do not add plagiarism warning here
"""
    )

    final_feedback = (feedback_json.get("final_feedback") or "").strip()
    strengths = [str(x).strip() for x in (feedback_json.get("strengths") or []) if str(x).strip()][:3]
    weaknesses = [str(x).strip() for x in (feedback_json.get("weaknesses") or []) if str(x).strip()][:3]
    next_steps = [str(x).strip() for x in (feedback_json.get("next_steps") or []) if str(x).strip()][:3]

#     qa_json = llm.generate_json(
#         system="You are the Feedback QA Agent. Return STRICT JSON only.",
#         user=f"""
# Check whether the score, reasons, and final feedback are consistent.

# Assignment title:
# {assignment_title}

# Reference answer:
# {reference_answer}

# Evaluation:
# {json.dumps(evaluation, ensure_ascii=False)}

# Final feedback:
# {json.dumps({
#     "final_feedback": final_feedback,
#     "strengths": strengths,
#     "weaknesses": weaknesses,
#     "next_steps": next_steps,
#     "grade": grade
# }, ensure_ascii=False)}

# Return STRICT JSON:
# {{
#   "quality_score": 0.0,
#   "issues": []
# }}

# Rules:
# - Lower the quality score if score and explanation do not match
# - Lower the quality score if the feedback is generic
# - Lower the quality score if a likely partially-correct answer was scored as zero
# - Lower the quality score if the feedback invents issues not present in evaluation
# """
#     )
    qa_json = {"quality_score": 1.0, "issues": ["QA skipped for bulk run"]}

    if _feedback_looks_generic(final_feedback, assignment_title, assignment_prompt):
        fb = _build_fallback_feedback(
            assignment_title=assignment_title,
            evaluation=evaluation,
            personalization_context=personalization_context,
            grade=grade,
        )
        final_feedback = fb["final_feedback"]
        strengths = fb["strengths"]
        weaknesses = fb["weaknesses"]
        next_steps = fb["next_steps"]


    qa_score = _safe_float(qa_json.get("quality_score", 0.0), 0.0)
    if (
        _feedback_looks_generic(final_feedback, assignment_title, assignment_prompt)
        or qa_score < 0.75
    ):
        fb = _build_fallback_feedback(
            assignment_title=assignment_title,
            evaluation=evaluation,
            personalization_context=personalization_context,
            grade=grade,
        )
        final_feedback = fb["final_feedback"]
        strengths = fb["strengths"]
        weaknesses = fb["weaknesses"]
        next_steps = fb["next_steps"]

    result = {
        "grade": grade,
        "confidence": round(
            _clamp(
                _safe_float(
                    feedback_json.get("confidence", evaluation["confidence"]),
                    evaluation["confidence"]
                ),
                0.0,
                1.0
            ),
            2
        ),
        "final_feedback": final_feedback,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "next_steps": next_steps,
        "concept_scores": evaluation["concept_scores"],
        "agents": {
            "rubric": rubric_questions,
            "correctness": evaluation,
            "personalization_context": personalization_context,
            "qa": qa_json,
        },
    }

    print("DEBUG grade:", grade)
    print("DEBUG result:", result)
    print("DEBUG final grade:", grade)
    print("DEBUG final feedback:", final_feedback)

    return result