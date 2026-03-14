import os
from dotenv import load_dotenv
load_dotenv()

import time
import re
import html
import requests
from datetime import datetime
from pathlib import Path
from pypdf import PdfReader

from get_submissions_assignments import add_token_to_fileurl, download_file

MOODLE_URL = os.getenv("MOODLE_URL", "http://localhost:8080/moodle")
MOODLE_TOKEN = os.getenv("MOODLE_TOKEN", "ef6d0d7a10b807c02a779fded5d568bf")
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

COURSE_ID = int(os.getenv("COURSE_ID", "2"))
ASSIGNMENT_ID = int(os.getenv("ASSIGNMENT_ID", "2"))

DOWNLOAD_DIR = Path("submissions_downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)


def strip_html(s: str) -> str:
    s = s or ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s+\n", "\n\n", s)
    return s.strip()


def extract_text_from_pdf(pdf_path: Path) -> str:
    try:
        reader = PdfReader(str(pdf_path))
        text = []
        for page in reader.pages:
            t = page.extract_text() or ""
            text.append(t)
        return "\n".join(text).strip()
    except Exception as e:
        print("❌ PDF extract error:", e)
        return ""


def moodle_call(wsfunction: str, **params):
    if not MOODLE_TOKEN:
        raise RuntimeError("MOODLE_TOKEN missing")
    url = f"{MOODLE_URL}/webservice/rest/server.php"
    payload = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": wsfunction,
        "moodlewsrestformat": "json",
        **params
    }
    r = requests.post(url, data=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("exception"):
        raise RuntimeError(f"Moodle error: {data.get('message')}")
    return data


def backend_get_existing(moodle_submission_id: int):
    try:
        r = requests.get(f"{BACKEND_URL}/submission/by_moodle/{moodle_submission_id}", timeout=15)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def get_assignment_info(course_id: int, assignment_id: int):
    data = moodle_call("mod_assign_get_assignments", **{"courseids[0]": course_id})
    for c in data.get("courses", []):
        for a in c.get("assignments", []):
            if a.get("id") == assignment_id:
                return {
                    "id": a.get("id"),
                    "name": a.get("name", ""),
                    "intro": strip_html(a.get("intro", "")),
                    "duedate": int(a.get("duedate") or 0),
                }
    return {"id": assignment_id, "name": "", "intro": "", "duedate": 0}


def get_submissions(assignment_id: int):
    data = moodle_call("mod_assign_get_submissions", **{"assignmentids[0]": assignment_id})
    return data.get("assignments", [])[0].get("submissions", [])


def get_submission_text(sub) -> str:
    plugins = sub.get("plugins", [])

    for p in plugins:
        if p.get("type") == "onlinetext":
            for ef in p.get("editorfields", []):
                txt = strip_html(ef.get("text") or "")
                if txt.strip():
                    return txt

            for fa in p.get("fileareas", []):
                txt = strip_html(fa.get("text") or "")
                if txt.strip():
                    return txt

    for p in plugins:
        if p.get("type") == "file":
            for fa in p.get("fileareas", []):
                for f in fa.get("files", []):
                    filename = f.get("filename", "")
                    fileurl = f.get("fileurl", "")
                    if not fileurl:
                        continue

                    if filename.lower().endswith(".pdf"):
                        out = DOWNLOAD_DIR / f"{sub.get('id')}_{sub.get('userid')}_{filename}"
                        print(f"⬇️ Downloading PDF: {filename}")
                        token_url = add_token_to_fileurl(fileurl)
                        download_file(token_url, out)

                        text = extract_text_from_pdf(out)
                        if text.strip():
                            return text
                        else:
                            print("⚠️ PDF has no extractable text.")
                            return ""

    return ""


def backend_post(path: str, payload: dict | None = None, params: dict | None = None):
    payload = payload or {}
    params = params or {}
    r = requests.post(f"{BACKEND_URL}{path}", json=payload, params=params, timeout=240)
    if r.status_code >= 400:
        print("❌ Backend error:", r.status_code, r.text[:700])
    r.raise_for_status()
    return r.json()


def push_grade_to_moodle(assign_id, user_id, grade, feedback):
    resp = moodle_call(
        "mod_assign_save_grade",
        assignmentid=assign_id,
        userid=user_id,
        grade=grade,
        attemptnumber=-1,
        addattempt=0,
        workflowstate="graded",
        applytoall=0,
        **{
            "plugindata[assignfeedbackcomments_editor][text]": str(feedback),
            "plugindata[assignfeedbackcomments_editor][format]": 1,
        }
    )
    print("Moodle grade push response:", resp)
    return resp


def main():
    assign = get_assignment_info(COURSE_ID, ASSIGNMENT_ID)
    due = assign["duedate"]
    now = int(time.time())

    print("Assignment:", assign["name"])
    print("Due date:", due, datetime.fromtimestamp(due).isoformat() if due else "None")
    print("Now:", now, datetime.fromtimestamp(now).isoformat())

    submissions = get_submissions(ASSIGNMENT_ID)
    print("Submissions found:", len(submissions))

    for sub in submissions:
        moodle_submission_id = sub.get("id")
        student_id = sub.get("userid")

        raw_text = get_submission_text(sub)

        if not raw_text.strip():
            print(f"⚠️ submission {moodle_submission_id} (user {student_id}) has no online text. PDF extraction needed.")
            continue

        print("DEBUG EXTRACTED:")
        print("  moodle submission id:", moodle_submission_id)
        print("  moodle user id:", student_id)
        print("  first 200 chars:", raw_text[:200])

        ingest = backend_post("/ingest/submission", {
            "moodle_submission_id": moodle_submission_id,
            "assignment_id": ASSIGNMENT_ID,
            "course_id": COURSE_ID,
            "student_id": student_id,
            "assignment_title": assign["name"],
            "assignment_prompt": assign["intro"],
            "raw_text": raw_text
        })
        submission_db_id = ingest["id"]
        print("✅ ingested/refreshed -> backend submission id:", submission_db_id)

        print("Debug: calling", f"{BACKEND_URL}/plagiarism/check/{submission_db_id}")
        try:
            backend_post(f"/plagiarism/check/{submission_db_id}", {}, params={"threshold": 0.90})
        except requests.exceptions.HTTPError as e:
            print("⚠️ plagiarism check failed:", str(e))
            continue

        if due and now < due:
            print("⏳ Before deadline -> NOT grading yet")
            continue

        graded = backend_post(f"/llm/multi_grade/{submission_db_id}", {})
        result = graded["multi_agent"]
        grade = float(result.get("grade", 0))
        feedback = result.get("final_feedback", "")

        print("DEBUG PUSH:")
        print("  moodle submission id:", moodle_submission_id)
        print("  moodle user id:", student_id)
        print("  backend submission id:", submission_db_id)
        print("  grade:", grade)
        print("  feedback:", feedback)

        push_grade_to_moodle(ASSIGNMENT_ID, student_id, grade, feedback)
        time.sleep(20)
        print(f"✅ pushed grade to Moodle user {student_id}: {grade}")


if __name__ == "__main__":
    main()