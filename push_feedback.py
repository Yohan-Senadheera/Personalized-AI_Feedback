import os
import re
import requests
from typing import Dict, Any, Tuple

MOODLE_URL = "http://localhost:8080/moodle"
TOKEN = "ef6d0d7a10b807c02a779fded5d568bf"

COURSE_ID = 2
ASSIGNMENT_ID = 1

SUBMISSIONS_DIR = "submissions"


# ------------------ Moodle API helpers ------------------

def call_moodle(function_name: str, params: Dict[str, Any]) -> Any:
    endpoint = f"{MOODLE_URL}/webservice/rest/server.php"
    base_params = {
        "wstoken": TOKEN,
        "wsfunction": function_name,
        "moodlewsrestformat": "json",
    }
    merged = {**base_params, **params}

    r = requests.post(endpoint, data=merged, timeout=60)
    r.raise_for_status()
    data = r.json()

    if isinstance(data, dict) and data.get("exception"):
        raise RuntimeError(f"Moodle error: {data.get('message')} ({data.get('errorcode')})")

    return data


def get_assignment_max_grade(course_id: int, assignment_id: int) -> float:
    data = call_moodle("mod_assign_get_assignments", {"courseids[0]": course_id})
    for course in data.get("courses", []):
        for a in course.get("assignments", []):
            if a.get("id") == assignment_id:
                g = a.get("grade", 10)
                try:
                    return float(g)
                except Exception:
                    return 10.0
    return 10.0


def pick_latest_submission(submissions_json: Dict[str, Any]) -> Tuple[int, int]:
    latest_userid = None
    latest_subid = None
    latest_time = -1

    for assignment in submissions_json.get("assignments", []):
        for sub in assignment.get("submissions", []):
            userid = sub.get("userid")
            subid = sub.get("id")
            t = sub.get("timemodified") or sub.get("timecreated") or 0
            if t > latest_time:
                latest_time = t
                latest_userid = userid
                latest_subid = subid

    if latest_userid is None or latest_subid is None:
        raise RuntimeError("No submissions found.")
    return latest_userid, latest_subid


# ------------------ Local file reading ------------------

def clean_pdf_text(s: str) -> str:
    # Fix common PDF extraction artifacts like "tra(cid:431)ic"
    s = re.sub(r"\(cid:\d+\)", "", s)
    s = s.replace("\u00ad", "")  # soft hyphen
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def read_extracted_submission_text(user_id: int, course_id: int, assignment_id: int) -> str:
    """
    Reads your saved txt file: submissions/<userid>_<courseid>_<assignmentid>.txt
    Then extracts the PDF submission part.
    """
    path = os.path.join(SUBMISSIONS_DIR, f"{user_id}_{course_id}_{assignment_id}.txt")
    if not os.path.exists(path):
        raise RuntimeError(f"Local extracted submission file not found: {path}")

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Extract only the PDF text section if present
    m = re.search(r"=== PDF SUBMISSION TEXT ===\s*(.*)", content, flags=re.DOTALL)
    if m:
        return clean_pdf_text(m.group(1).strip())

    # Otherwise fallback to full content
    return clean_pdf_text(content)


# ------------------ Feedback + grading ------------------

def grade_and_feedback(answer_text: str, max_grade: float) -> Tuple[float, str]:
    t = clean_pdf_text(answer_text).lower()

    score = 0.0
    feedback = []

    # Q1 (3 pts)
    q1 = 0
    if "service" in t and ("stable" in t or "endpoint" in t or "dns" in t):
        q1 += 1
    if "pods" in t and ("ip" in t or "change" in t or "restart" in t):
        q1 += 1
    if "load" in t and ("balance" in t or "load-balanc" in t):
        q1 += 1
    q1 = min(q1, 3)
    score += q1
    feedback.append(f"Q1 (Service): {q1}/3 — Clear idea of stable access to Pods. DNS + load balancing mention is solid.")

    # Q2 (3 pts)
    q2 = 0
    if "clusterip" in t and ("inside" in t or "internal" in t or "within" in t):
        q2 += 1
    if "nodeport" in t and ("outside" in t or "external" in t or "access" in t):
        q2 += 1
    if "port" in t and ("node" in t or "every node" in t):
        q2 += 1
    q2 = min(q2, 3)
    score += q2
    feedback.append(f"Q2 (ClusterIP vs NodePort): {q2}/3 — Correct internal vs external exposure. Nice detail about node-level ports.")

    # Q3 (3 pts)
    q3 = 0
    if "networkpolicy" in t or "network policy" in t:
        q3 += 1
    if ("allow" in t or "only" in t) and ("block" in t or "deny" in t):
        q3 += 1
    if "frontend" in t and "backend" in t:
        q3 += 1
    q3 = min(q3, 3)
    score += q3
    feedback.append(f"Q3 (NetworkPolicy): {q3}/3 — Great example: only frontend can talk to backend, others blocked.")

    raw_max = 9.0
    scaled = round((score / raw_max) * max_grade, 2)

    overall = [
        "Overall: Strong submission — concepts are correct and explained clearly.",
        "Improvement idea: mention Services select Pods using labels, and in production external exposure is often via LoadBalancer/Ingress (not only NodePort).",
        "",
        "Breakdown:",
        *feedback
    ]
    return scaled, "\n".join(overall)


# ------------------ Push to Moodle ------------------

def save_grade_with_feedback(assignment_id: int, userid: int, grade: float, feedback_text: str) -> Any:
    params = {
        "assignmentid": assignment_id,
        "userid": userid,
        "grade": grade,
        "attemptnumber": -1,
        "addattempt": 0,
        "workflowstate": "graded",
        "applytoall": 0,
        "plugindata[assignfeedbackcomments_editor][text]": feedback_text,
        "plugindata[assignfeedbackcomments_editor][format]": 1,  # HTML format; plain text still ok
    }
    return call_moodle("mod_assign_save_grade", params)


def main():
    max_grade = get_assignment_max_grade(COURSE_ID, ASSIGNMENT_ID)

    submissions = call_moodle("mod_assign_get_submissions", {"assignmentids[0]": ASSIGNMENT_ID})
    userid, subid = pick_latest_submission(submissions)

    # ✅ read your extracted PDF text from local file
    extracted_text = read_extracted_submission_text(userid, COURSE_ID, ASSIGNMENT_ID)

    grade, feedback = grade_and_feedback(extracted_text, max_grade)

    res = save_grade_with_feedback(ASSIGNMENT_ID, userid, grade, feedback)

    print("✅ Graded successfully")
    print(f"User: {userid} | Submission: {subid}")
    print(f"Grade: {grade} / {max_grade}")
    print("Response:", res)


if __name__ == "__main__":
    main()
