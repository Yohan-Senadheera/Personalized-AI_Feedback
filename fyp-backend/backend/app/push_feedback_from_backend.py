import requests

MOODLE_URL = "http://localhost:8080/moodle"
TOKEN = "YOUR_TOKEN"
BACKEND_URL = "http://127.0.0.1:8000"

def moodle_call(function_name, params):
    url = f"{MOODLE_URL}/webservice/rest/server.php"
    payload = {
        "wstoken": TOKEN,
        "wsfunction": function_name,
        "moodlewsrestformat": "json",
        **params
    }
    r = requests.post(url, data=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def main():
    # choose which submission to push
    submission_id = 14  # your internal DB submission id

    # 1) get payload from backend
    pkg = requests.get(f"{BACKEND_URL}/moodle/push_payload/{submission_id}", timeout=30).json()

    assign_id = pkg["moodle_assign_id"]
    user_id = pkg["moodle_user_id"]
    grade = pkg["grade"]
    feedback = pkg["feedback_text"]

    # 2) push grade + feedback to Moodle
    res = moodle_call("mod_assign_save_grade", {
        "assignmentid": assign_id,
        "userid": user_id,
        "grade": grade,
        "attemptnumber": -1,
        "addattempt": 0,
        "workflowstate": "",
        "applytoall": 0,
        "plugindata[assignfeedbackcomments_editor][text]": feedback,
        "plugindata[assignfeedbackcomments_editor][format]": 1
    })

    print("✅ Moodle response:", res)

if __name__ == "__main__":
    main()
