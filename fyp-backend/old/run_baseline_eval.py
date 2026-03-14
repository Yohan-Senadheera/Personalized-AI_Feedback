import os
import sys
import json
import pandas as pd
from tqdm import tqdm

sys.path.append(os.getcwd())

from backend.app.llm import get_llm

INPUT_FILE = "evaluation_asag_multi.csv"
OUTPUT_FILE = "evaluation_asag_full.csv"

def safe_text(x):
    if pd.isna(x):
        return ""
    return str(x).strip()

def main():
    df = pd.read_csv(INPUT_FILE)
    llm = get_llm()

    grades = []
    feedbacks = []

    for _, row in tqdm(df.iterrows(), total=len(df), desc="Baseline grading"):
        question = safe_text(row["assignment"])
        ref_answer = safe_text(row["reference_answer"])
        student_answer = safe_text(row["student_answer"])

        system = "You are a strict academic grader. Return STRICT JSON only."

        user = f"""
Grade this short-answer response against the question and instructor reference answer.

Question:
{question}

Instructor reference answer:
{ref_answer}

Student answer:
{student_answer}

Return STRICT JSON:
{{
  "grade": 0,
  "feedback": "short specific feedback"
}}

Rules:
- grade must be an integer from 0 to 100
- be strict but fair
- reward conceptually correct answers even if wording differs
- do not use markdown
- feedback must match the assigned grade
"""

        try:
            result = llm.generate_json(system=system, user=user)
            grade = int(round(float(result.get("grade", 0))))
            grade = max(0, min(100, grade))
            feedback = str(result.get("feedback", "")).strip()
        except Exception as e:
            print(f"[ERROR] sample {row['sample_id']}: {e}")
            grade = ""
            feedback = f"ERROR: {e}"

        grades.append(grade)
        feedbacks.append(feedback)

    df["baseline_grade"] = grades
    df["baseline_feedback"] = feedbacks

    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
    print(f"[OK] wrote {OUTPUT_FILE}")

if __name__ == "__main__":
    main()