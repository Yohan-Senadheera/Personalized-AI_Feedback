import os, time, json, requests
from datetime import datetime, timezone
from pathlib import Path
from pypdf import PdfReader

from get_submissions_assignments import add_token_to_fileurl, download_file

MOODLE_URL = os.getenv("MOODLE_URL", "http://localhost:8080/moodle")
MOODLE_TOKEN = os.getenv("MOODLE_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

COURSE_ID = int(os.getenv("COURSE_ID", "2"))  # your course id=2
ASSIGNMENT_ID = int(os.getenv("ASSIGNMENT_ID", "1"))  # your assignment id=1

DOWNLOAD_DIR = Path("submissions_downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

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

def download_moodle_file(fileurl: str, out_path: Path) -> Path:
    # Moodle needs token appended to fileurl
    
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    out_path.write_bytes(r.content)
    return out_path
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


def backend_submission_exists(moodle_submission_id: int):
    try:
        r = requests.get(
            f"{BACKEND_URL}/submission/by_moodle/{moodle_submission_id}",
            timeout=10
        )
        return r.status_code == 200
    except:
        return False

def get_assignment_due_date(course_id: int, assignment_id: int) -> int:
    data = moodle_call(
        "mod_assign_get_assignments",
        **{"courseids[0]": course_id}
    )

    for c in data.get("courses", []):
        for a in c.get("assignments", []):
            if a.get("id") == assignment_id:
                return int(a.get("duedate") or 0)

    return 0


def get_submissions(assignment_id: int):
    data = moodle_call(
    "mod_assign_get_submissions",
    **{"assignmentids[0]": assignment_id}
)
    return data.get("assignments", [])[0].get("submissions", [])

def get_submission_text(sub) -> str:
    plugins = sub.get("plugins", [])

    # 1) Try online text first (if exists)
    for p in plugins:
        if p.get("type") == "onlinetext":
            # sometimes stored directly under "editorfields"
            for ef in p.get("editorfields", []):
                txt = ef.get("text") or ""
                if txt.strip():
                    return txt

            # some moodle versions store it differently
            for fa in p.get("fileareas", []):
                txt = fa.get("text") or ""
                if txt and txt.strip():
                    return txt

    # 2) Try file upload (PDF/DOCX/etc.)
    for p in plugins:
        if p.get("type") == "file":
            for fa in p.get("fileareas", []):
                for f in fa.get("files", []):
                    filename = f.get("filename", "")
                    fileurl = f.get("fileurl", "")
                    if not fileurl:
                        continue

                    # Only handle PDFs for now
                    if filename.lower().endswith(".pdf"):
                        out = DOWNLOAD_DIR / f"{sub.get('id')}_{sub.get('userid')}_{filename}"
                        print(f"⬇️ Downloading PDF: {filename}")
                        token_url = add_token_to_fileurl(fileurl)
                        download_file(token_url, out)

                        text = extract_text_from_pdf(out)
                        if text.strip():
                            return text
                        else:
                            print("⚠️ PDF has no extractable text (maybe scanned image).")
                            return ""

    return ""


def backend_post(path: str, payload: dict | None = None, params: dict | None = None):
    payload = payload or {}
    params = params or {}
    r = requests.post(f"{BACKEND_URL}{path}", json=payload, params=params, timeout=180)
    # debug if error
    if r.status_code >= 400:
        print("❌ Backend error:", r.status_code, r.text[:300])
    r.raise_for_status()
    return r.json()


def push_grade_to_moodle(assign_id: int, user_id: int, grade: float, feedback: str):
    # ✅ Moodle grading function
    # Note: Some Moodle configs require additional params like attemptnumber, addattempt, workflowstate.
    resp = moodle_call(
        "mod_assign_save_grade",
        assignmentid=assign_id,
        userid=user_id,
        grade=str(grade),
        attemptnumber=-1,
        addattempt=0,
        workflowstate="graded",
        feedbacktext=feedback,
        feedbackformat=1,  # 1=HTML, 0=MOODLE, 2=PLAIN depending on Moodle config
    )
    return resp

def backend_get_existing(moodle_submission_id: int):
    try:
        r = requests.get(f"{BACKEND_URL}/submission/by_moodle/{moodle_submission_id}", timeout=15)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None

def main():
    due = get_assignment_due_date(COURSE_ID, ASSIGNMENT_ID)
    now = int(time.time())
    print("Due date:", due, datetime.fromtimestamp(due).isoformat() if due else "None")
    print("Now:", now, datetime.fromtimestamp(now).isoformat())

    submissions = get_submissions(ASSIGNMENT_ID)
    print("Submissions found:", len(submissions))

    for sub in submissions:
        moodle_submission_id = sub.get("id")
        student_id = sub.get("userid")

        existing = backend_get_existing(moodle_submission_id)
        if existing:
            print(f"⏭️ submission {moodle_submission_id} already ingested as backend id={existing['id']} (status={existing.get('status')}). Skipping.")
            continue

        # 1) Extract text
        raw_text = get_submission_text(sub)

        # If empty, skip for now (later plug PDF extractor)
        if not raw_text.strip():
            print(f"⚠️ submission {moodle_submission_id} (user {student_id}) has no online text. PDF extraction needed.")
            continue
        
        if backend_submission_exists(moodle_submission_id):
            print(f"⏭️ submission {moodle_submission_id} already ingested. Skipping.")
            continue

        # 2) Ingest into backend
        ingest = backend_post("/ingest/submission", {
            "moodle_submission_id": moodle_submission_id,
            "assignment_id": ASSIGNMENT_ID,
            "course_id": COURSE_ID,
            "student_id": student_id,
            "raw_text": raw_text
        })
        submission_db_id = ingest["id"]
        print("✅ ingested -> backend submission id:", submission_db_id)

        print("Debug: calling", f"{BACKEND_URL}/plagiarism/check/{submission_db_id}")

        # 3) Plagiarism check (always)
        try:
            plag = backend_post(f"/plagiarism/check/{submission_db_id}", {}, params={"threshold": 0.85})
        except requests.exceptions.HTTPError as e:
            print("⚠️ plagiarism check failed:", str(e))
            continue


        # 4) Deadline gating
        if due and now < due:
            print("⏳ Before deadline -> NOT grading yet (waiting_deadline)")
            # optional: add backend endpoint to set status waiting_deadline
            continue

        # 5) After deadline -> grade
        graded = backend_post(f"/llm/multi_grade/{submission_db_id}", {})
        result = graded["multi_agent"]
        grade = float(result.get("grade", 0))
        feedback = result.get("final_feedback", "")

        # 6) Push to Moodle
        push_grade_to_moodle(ASSIGNMENT_ID, student_id, grade, feedback)
        print(f"✅ pushed grade to Moodle user {student_id}: {grade}")

if __name__ == "__main__":
    main()

