import os
import re
import html
import requests
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import pdfplumber

# ✅ YOUR SETTINGS
MOODLE_URL = "http://localhost:8080/moodle"
TOKEN = "ef6d0d7a10b807c02a779fded5d568bf"
COURSE_ID = 2

# Put 0 first -> script will print assignments + tell you what to set
ASSIGNMENT_ID = 1

ASSIGNMENTS_DIR = "assignments"
SUBMISSIONS_DIR = "submissions"


def call_moodle(function_name: str, params: dict) -> dict:
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


def add_token_to_fileurl(fileurl: str) -> str:
    parts = urlparse(fileurl)
    q = dict(parse_qsl(parts.query))
    q["token"] = TOKEN
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, urlencode(q), parts.fragment))


def safe_name(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", s).strip("_")


def strip_html_to_text(html_string: str) -> str:
    """Lightweight HTML -> text (no external libs)."""
    if not html_string:
        return ""
    s = html.unescape(html_string)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p\s*>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s).strip()
    return s


def download_file(url: str, out_path: str) -> None:
    dir_name = os.path.dirname(out_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(out_path, "wb") as fp:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    fp.write(chunk)


def preview_pdf_text(pdf_path: str, max_chars: int = 30000) -> str:
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t.strip():
                parts.append(t)
    text = "\n\n".join(parts).strip()

    if not text:
        return "(No extractable text - may be scanned/image PDF)"

    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text


def extract_submission_files_and_text(submissions_json: dict):
    files = []
    texts = []

    for assignment in submissions_json.get("assignments", []):
        for sub in assignment.get("submissions", []):
            userid = sub.get("userid")
            submissionid = sub.get("id")

            for plugin in sub.get("plugins", []):
                # 1) FILES
                for area in plugin.get("fileareas", []):
                    for f in area.get("files", []):
                        files.append({
                            "userid": userid,
                            "submissionid": submissionid,
                            "filename": f.get("filename"),
                            "fileurl": f.get("fileurl"),
                            "mimetype": f.get("mimetype"),
                        })

                # 2) ONLINE TEXT
                for ef in plugin.get("editorfields", []):
                    name = ef.get("name") or "editorfield"
                    html_text = ef.get("text") or ef.get("content") or ""
                    if html_text and html_text.strip():
                        texts.append({
                            "userid": userid,
                            "submissionid": submissionid,
                            "fieldname": name,
                            "html": html_text,
                            "plain": strip_html_to_text(html_text),
                        })

    return files, texts


def save_assignment_master(assignments_dir: str, course_id: int, assignment_id: int, content: str) -> str:
    os.makedirs(assignments_dir, exist_ok=True)
    path = os.path.join(assignments_dir, f"{course_id}_{assignment_id}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Saved assignment: {path}")
    return path


def save_student_submission_text(submissions_dir: str, student_id: int, course_id: int, assignment_id: int, content: str):
    os.makedirs(submissions_dir, exist_ok=True)
    filename = f"{student_id}_{course_id}_{assignment_id}.txt"
    path = os.path.join(submissions_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Saved submission: {path}")


def get_course_assignments(course_id: int) -> list[dict]:
    data = call_moodle("mod_assign_get_assignments", {"courseids[0]": course_id})
    for course in data.get("courses", []):
        if course.get("id") == course_id:
            return course.get("assignments", [])
    return []


def extract_assignment_files(assignment_obj: dict) -> list[dict]:
    files = []
    for key in ("introfiles", "introattachments"):
        for f in assignment_obj.get(key, []) or []:
            files.append({
                "filename": f.get("filename"),
                "fileurl": f.get("fileurl"),
                "mimetype": f.get("mimetype", ""),
                "source": key
            })
    return files


def main():
    # 1) List assignments in the course
    assignments = get_course_assignments(COURSE_ID)

    if not assignments:
        print("❌ No assignments found in this course yet.")
        print("👉 Create an Assignment in course id=2, then run again.")
        return

    print("\n📌 Assignments found in course:")
    for a in assignments:
        print(f"  - ASSIGNMENT_ID: {a.get('id')} | NAME: {a.get('name')}")

    if ASSIGNMENT_ID == 0:
        print("\n✅ Now pick one ASSIGNMENT_ID from above and set ASSIGNMENT_ID in the code.")
        return

    # 2) Find the selected assignment object
    assignment = None
    for a in assignments:
        if a.get("id") == ASSIGNMENT_ID:
            assignment = a
            break

    if assignment is None:
        raise RuntimeError(f"❌ ASSIGNMENT_ID={ASSIGNMENT_ID} not found in course {COURSE_ID}.")

    # 3) Build master assignment text
    assign_name = assignment.get("name", "")
    intro_html = assignment.get("intro", "")
    intro_text = strip_html_to_text(intro_html)

    master_sections = []
    master_sections.append(f"COURSE ID: {COURSE_ID}")
    master_sections.append(f"ASSIGNMENT ID: {ASSIGNMENT_ID}")
    master_sections.append(f"ASSIGNMENT NAME: {assign_name}\n")
    master_sections.append("=== DESCRIPTION / INSTRUCTIONS (FROM INTRO) ===")
    master_sections.append(intro_text if intro_text else "(No intro text found)")

    # 4) Download + extract text from assignment PDF attachments (if any)
    assignment_files = extract_assignment_files(assignment)
    if assignment_files:
        master_sections.append("\n=== ASSIGNMENT ADDITIONAL FILES (EXTRACTED TEXT) ===")
        for af in assignment_files:
            fname = af["filename"] or "file"
            furl = af["fileurl"]
            mm = (af["mimetype"] or "").lower()
            master_sections.append(f"\n--- File: {fname} (from {af['source']}) ---")

            if not furl:
                master_sections.append("(No fileurl)")
                continue

            is_pdf = ("pdf" in mm) or fname.lower().endswith(".pdf")
            if not is_pdf:
                master_sections.append("(Skipped: not a PDF)")
                continue

            tmp = f"tmp_assignment_{safe_name(fname)}"
            token_url = add_token_to_fileurl(furl)
            download_file(token_url, tmp)

            try:
                txt = preview_pdf_text(tmp, max_chars=30000)
                master_sections.append(txt)
            except Exception as e:
                master_sections.append(f"(Failed to extract PDF text: {e})")
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
    else:
        master_sections.append("\n=== ASSIGNMENT ADDITIONAL FILES ===\n(None found)")

    master_text = "\n".join(master_sections)
    save_assignment_master(ASSIGNMENTS_DIR, COURSE_ID, ASSIGNMENT_ID, master_text)

    # 5) Fetch submissions
    submissions = call_moodle("mod_assign_get_submissions", {"assignmentids[0]": ASSIGNMENT_ID})
    files, texts = extract_submission_files_and_text(submissions)

    # 6) Merge content per student
    submission_map = {}

    for t in texts:
        key = (t["userid"], t["submissionid"])
        submission_map.setdefault(key, [])
        submission_map[key].append("=== ONLINE TEXT SUBMISSION ===\n" + t["plain"] + "\n")

    for f in files:
        filename = f["filename"] or ""
        mimetype = (f["mimetype"] or "").lower()
        is_pdf = ("pdf" in mimetype) or filename.lower().endswith(".pdf")

        if not is_pdf or not f["fileurl"]:
            continue

        key = (f["userid"], f["submissionid"])
        submission_map.setdefault(key, [])

        token_url = add_token_to_fileurl(f["fileurl"])
        temp_pdf = f"temp_{f['userid']}_{f['submissionid']}_{safe_name(filename)}"
        download_file(token_url, temp_pdf)

        try:
            pdf_text = preview_pdf_text(temp_pdf, max_chars=30000)
        except Exception:
            pdf_text = "(PDF text extraction failed)"
        finally:
            if os.path.exists(temp_pdf):
                os.remove(temp_pdf)

        submission_map[key].append("=== PDF SUBMISSION TEXT ===\n" + pdf_text + "\n")

    # 7) Save output files
    if not submission_map:
        print("\n⚠️ No submissions found yet for this assignment.")
    else:
        for (student_id, submission_id), parts in submission_map.items():
            final_text = (
                f"STUDENT ID: {student_id}\n"
                f"COURSE ID: {COURSE_ID}\n"
                f"ASSIGNMENT ID: {ASSIGNMENT_ID}\n"
                f"SUBMISSION ID: {submission_id}\n\n"
                + "\n".join(parts)
            )
            save_student_submission_text(SUBMISSIONS_DIR, student_id, COURSE_ID, ASSIGNMENT_ID, final_text)

    print("\n✅ All processed.")


if __name__ == "__main__":
    main()