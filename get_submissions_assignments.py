import os
import time
import re
import html
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import pdfplumber

# =========================
# CONFIG (edit or use env)
# =========================
MOODLE_URL = os.getenv("MOODLE_URL", "http://localhost:8080/moodle")
MOODLE_TOKEN = os.getenv("MOODLE_TOKEN", "ef6d0d7a10b807c02a779fded5d568bf")

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

COURSE_ID = int(os.getenv("COURSE_ID", "2"))
ASSIGNMENT_ID = int(os.getenv("ASSIGNMENT_ID", "1"))

PLAG_THRESHOLD = float(os.getenv("PLAG_THRESHOLD", "0.85"))

# Save downloaded PDFs here
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "submissions_downloads"))
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Token cap for extracted text (avoid massive payloads)
MAX_EXTRACT_CHARS = int(os.getenv("MAX_EXTRACT_CHARS", "30000"))


# =========================
# Moodle helpers
# =========================
def moodle_call(wsfunction: str, **params):
    """
    Moodle REST API call.
    Important: to pass array params use: **{"courseids[0]": 2}
    """
    endpoint = f"{MOODLE_URL}/webservice/rest/server.php"
    base_params = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": wsfunction,
        "moodlewsrestformat": "json",
    }
    merged = {**base_params, **params}
    r = requests.post(endpoint, data=merged, timeout=60)
    r.raise_for_status()
    data = r.json()

    if isinstance(data, dict) and data.get("exception"):
        raise RuntimeError(f"Moodle error: {data.get('message')} ({data.get('errorcode')})")

    return data


def add_token_to_fileurl(fileurl: str) -> str:
    parts = urlparse(fileurl)
    q = dict(parse_qsl(parts.query))
    q["token"] = MOODLE_TOKEN
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, urlencode(q), parts.fragment))


def safe_name(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", s).strip("_")


def strip_html_to_text(html_string: str) -> str:
    if not html_string:
        return ""
    s = html.unescape(html_string)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p\s*>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s).strip()
    return s


def download_file(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(out_path, "wb") as fp:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    fp.write(chunk)


def extract_text_from_pdf(pdf_path: Path, max_chars: int = 30000) -> str:
    parts = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    parts.append(t)
        text = "\n\n".join(parts).strip()

        if not text:
            return ""

        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text

    except Exception as e:
        print("❌ pdfplumber extract error:", e)
        return ""


# =========================
# Backend helpers
# =========================
def backend_post(path: str, payload: dict | None = None):
    payload = payload or {}
    r = requests.post(f"{BACKEND_URL}{path}", json=payload, timeout=180)
    r.raise_for_status()
    return r.json()


# =========================
# Moodle grade push
# =========================
def push_grade_to_moodle(assign_id: int, user_id: int, grade: float, feedback: str):
    """
    Push grade + feedback to Moodle.
    NOTE: feedbackformat may differ depending on Moodle config.
    1 = HTML is usually fine.
    """
    return moodle_call(
        "mod_assign_save_grade",
        **{
            "assignmentid": assign_id,
            "userid": user_id,
            "grade": str(grade),
            "attemptnumber": -1,
            "addattempt": 0,
            "workflowstate": "graded",
            "feedbacktext": feedback,
            "feedbackformat": 1,
        }
    )


# =========================
# Fetch due date + submissions
# =========================
def get_assignment_due_date(course_id: int, assignment_id: int) -> int:
    data = moodle_call("mod_assign_get_assignments", **{"courseids[0]": course_id})
    for c in data.get("courses", []):
        for a in c.get("assignments", []):
            if a.get("id") == assignment_id:
                return int(a.get("duedate") or 0)
    return 0


def get_submissions(assignment_id: int) -> list[dict]:
    data = moodle_call("mod_assign_get_submissions", **{"assignmentids[0]": assignment_id})
    assignments = data.get("assignments", [])
    if not assignments:
        return []
    return assignments[0].get("submissions", []) or []


# =========================
# Extract submission text (online or PDF)
# =========================
def get_submission_text(sub: dict) -> str:
    plugins = sub.get("plugins", [])

    # 1) Try online text first
    for p in plugins:
        if p.get("type") == "onlinetext":
            for ef in p.get("editorfields", []):
                html_text = ef.get("text") or ef.get("content") or ""
                plain = strip_html_to_text(html_text)
                if plain.strip():
                    return plain

    # 2) Try files (PDF)
    for p in plugins:
        if p.get("type") == "file":
            for area in p.get("fileareas", []):
                for f in area.get("files", []):
                    filename = f.get("filename") or ""
                    fileurl = f.get("fileurl") or ""
                    mimetype = (f.get("mimetype") or "").lower()

                    is_pdf = ("pdf" in mimetype) or filename.lower().endswith(".pdf")
                    if not is_pdf or not fileurl:
                        continue

                    token_url = add_token_to_fileurl(fileurl)

                    out = DOWNLOAD_DIR / f"{sub.get('id')}_{sub.get('userid')}_{safe_name(filename)}"
                    print(f"⬇️ Downloading PDF: {filename}")
                    download_file(token_url, out)

                    # sanity check: must start with %PDF
                    head = out.read_bytes()[:4]
                    if head != b"%PDF":
                        print("❌ Not a PDF. First bytes:", head)
                        # Print first 200 chars for debugging (often JSON error)
                        try:
                            txt = out.read_text(errors="ignore")[:200]
                            print("Response preview:", txt)
                        except Exception:
                            pass
                        return ""

                    text = extract_text_from_pdf(out, max_chars=MAX_EXTRACT_CHARS)
                    if text.strip():
                        return text

                    print("⚠️ PDF has no extractable text (maybe scanned/image PDF).")
                    return ""

    return ""


# =========================
# MAIN PIPELINE
# =========================
def main():
    due = get_assignment_due_date(COURSE_ID, ASSIGNMENT_ID)
    now = int(time.time())

    print("Due date:", due, datetime.fromtimestamp(due).isoformat() if due else "None")
    print("Now:", now, datetime.fromtimestamp(now).isoformat())

    subs = get_submissions(ASSIGNMENT_ID)
    print("Submissions found:", len(subs))

    for sub in subs:
        moodle_submission_id = sub.get("id")
        student_id = sub.get("userid")

        raw_text = get_submission_text(sub)

        if not raw_text.strip():
            print(f"⚠️ submission {moodle_submission_id} (user {student_id}) text empty. (online text missing + pdf failed or scanned)")
            continue

        # 1) Ingest -> backend
        ingest = backend_post("/ingest/submission", {
            "moodle_submission_id": moodle_submission_id,
            "assignment_id": ASSIGNMENT_ID,
            "course_id": COURSE_ID,
            "student_id": student_id,
            "raw_text": raw_text
        })
        submission_db_id = ingest["id"]
        print(f"✅ ingested submission {moodle_submission_id} -> backend id: {submission_db_id}")

        # 2) Plagiarism check
        plag = backend_post(f"/plagiarism/check/{submission_db_id}?threshold={PLAG_THRESHOLD}", {})
        print(f"🔎 plagiarism flagged_count={plag.get('flagged_count', 0)} for backend submission {submission_db_id}")

        # 3) Deadline gating
        if due and now < due:
            print("⏳ Before deadline -> NOT grading yet (waiting_deadline)")
            continue

        # 4) After deadline -> grade
        graded = backend_post(f"/llm/multi_grade/{submission_db_id}", {})
        result = graded.get("multi_agent", {})
        grade = float(result.get("grade", 0))
        feedback = result.get("final_feedback", "")

        # Optional: if flagged, don’t auto-push grade
        if plag.get("flagged_count", 0) > 0:
            feedback = "⚠️ Plagiarism warning: similarity flagged.\n\n" + feedback
            # You can choose to skip pushing grade here if you want:
            # print("🚫 Flagged plagiarism -> skipping grade push (needs manual review)")
            # continue

        # 5) Push grade to Moodle
        push_grade_to_moodle(ASSIGNMENT_ID, student_id, grade, feedback)
        print(f"✅ pushed to Moodle | user={student_id} grade={grade}")

    print("\n✅ Scheduler run complete.")


if __name__ == "__main__":
    main()
