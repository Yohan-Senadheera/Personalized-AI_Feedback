import re

def grade_networking_short_answer(q_chunks: dict[int, str], max_grade: float = 100.0):
    """
    Simple rubric-based grader for your 3 questions.
    Returns (grade, feedback_text, feedback_json)
    """
    def norm(s: str) -> str:
        s = re.sub(r"\(cid:\d+\)", "", s)
        return s.lower()

    score = 0.0
    feedback = []

    # Q1 /3
    q1 = norm(q_chunks.get(1, ""))
    pts1 = 0
    if "service" in q1 and ("stable" in q1 or "endpoint" in q1 or "dns" in q1):
        pts1 += 1
    if "pod" in q1 and ("ip" in q1 or "restart" in q1 or "change" in q1):
        pts1 += 1
    if "load" in q1 and ("balance" in q1 or "balanc" in q1):
        pts1 += 1
    pts1 = min(pts1, 3)
    score += pts1
    feedback.append(f"Q1: {pts1}/3 — Service concept explained well.")

    # Q2 /3
    q2 = norm(q_chunks.get(2, ""))
    pts2 = 0
    if "clusterip" in q2 and ("internal" in q2 or "inside" in q2 or "within" in q2):
        pts2 += 1
    if "nodeport" in q2 and ("external" in q2 or "outside" in q2):
        pts2 += 1
    if "node" in q2 and "port" in q2:
        pts2 += 1
    pts2 = min(pts2, 3)
    score += pts2
    feedback.append(f"Q2: {pts2}/3 — ClusterIP vs NodePort is mostly correct.")

    # Q3 /3
    q3 = norm(q_chunks.get(3, ""))
    pts3 = 0
    if "networkpolicy" in q3 or "network policy" in q3:
        pts3 += 1
    if ("allow" in q3 or "only" in q3) and ("block" in q3 or "deny" in q3):
        pts3 += 1
    if "frontend" in q3 and "backend" in q3:
        pts3 += 1
    pts3 = min(pts3, 3)
    score += pts3
    feedback.append(f"Q3: {pts3}/3 — Good example of restricting traffic.")

    raw_max = 9.0
    grade = round((score / raw_max) * max_grade, 2)

    overall = "Overall: Solid answers. Improve by mentioning Services select Pods using labels; and for external access, LoadBalancer/Ingress are common."
    feedback_text = overall + "\n\n" + "\n".join(feedback)

    feedback_json = {
        "q1": pts1, "q2": pts2, "q3": pts3,
        "raw_score": score, "raw_max": raw_max
    }

    return grade, feedback_text, feedback_json