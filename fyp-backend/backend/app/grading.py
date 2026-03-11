from backend.app.multi_agent import run_multi_agent


def grade_networking_short_answer(q_chunks: dict[int, str], max_grade: float = 100.0):
    """
    Backward-compatible wrapper.
    It now uses the generic multi-agent Gemini grader instead of hardcoded Kubernetes rules.
    """
    result = run_multi_agent(
        q_chunks,
        student_context={
            "student_id": None,
            "weak_concepts": [],
            "trend": "unknown",
            "last_feedback_summary": "",
            "recent_grades": [],
            "recent_feedback_summaries": [],
            "recent_concepts": [],
            "plagiarism_flag": False,
        },
        assignment_context={
            "assignment_title": "Assignment",
            "assignment_prompt": "",
        },
    )
    return float(result.get("grade", 0)), result.get("final_feedback", ""), result