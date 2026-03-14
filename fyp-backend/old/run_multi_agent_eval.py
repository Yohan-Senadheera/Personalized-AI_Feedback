import os
import sys
import pandas as pd
from tqdm import tqdm

sys.path.append(os.getcwd())

from backend.app.multi_agent import run_multi_agent

INPUT_FILE = "evaluation_asag.csv"
OUTPUT_FILE = "evaluation_asag_multi.csv"


def safe_text(x):
    if pd.isna(x):
        return ""
    return str(x).strip()


def main():
    if os.path.exists(OUTPUT_FILE):
        df = pd.read_csv(OUTPUT_FILE)
        print(f"[RESUME] loaded existing {OUTPUT_FILE}")
    else:
        df = pd.read_csv(INPUT_FILE)

    for col in ["ai_grade_multi", "ai_feedback_multi", "ai_confidence_multi", "model_name", "prompt_version"]:
        if col not in df.columns:
            df[col] = ""

    for col in ["ai_grade_multi", "ai_feedback_multi", "ai_confidence_multi", "model_name", "prompt_version"]:
        df[col] = df[col].astype("object")

    for idx, row in tqdm(df.iterrows(), total=len(df), desc="Multi-agent grading"):
        existing_grade = str(row.get("ai_grade_multi", "")).strip()
        if existing_grade not in ("", "nan", "None"):
            continue

        question = safe_text(row["assignment"])
        ref_answer = safe_text(row["reference_answer"])
        student_answer = safe_text(row["student_answer"])

        qmap = {
            1: student_answer
        }

        assignment_context = {
            "assignment_title": f"ASAG Question {row['sample_id']}",
            "assignment_prompt": f"1. {question}",
            "reference_answer": ref_answer,
            "dataset_name": "ASAG",
            "dataset_max_score": 2,
        }

        student_context = {
            "weak_concepts": [],
            "trend": "unknown",
            "recent_grades": [],
            "recent_feedback_summaries": [],
            "recent_concepts": [],
            "plagiarism_flag": False,
        }

        try:
            result = run_multi_agent(
                qmap=qmap,
                student_context=student_context,
                assignment_context=assignment_context,
            )
            df.at[idx, "ai_grade_multi"] = result.get("grade", "")
            df.at[idx, "ai_feedback_multi"] = result.get("final_feedback", "")
            df.at[idx, "ai_confidence_multi"] = result.get("confidence", "")

        except Exception as e:
            print(f"[ERROR] sample {row['sample_id']}: {e}")
            df.at[idx, "ai_grade_multi"] = ""
            df.at[idx, "ai_feedback_multi"] = f"ERROR: {e}"
            df.at[idx, "ai_confidence_multi"] = ""

        df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    print(f"[OK] wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()