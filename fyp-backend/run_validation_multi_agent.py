import os
import sys
import pandas as pd
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.getcwd())

from backend.app.multi_agent import run_multi_agent
from backend.app.config import LLM_MODE

INPUT_FILE = "evaluation_validation.csv"
OUTPUT_FILE = f"evaluation_validation_{LLM_MODE}.csv"


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

    for idx, row in tqdm(df.iterrows(), total=len(df), desc=f"Validation grading ({LLM_MODE})"):
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
            "assignment_title": f"Validation Sample {row['sample_id']}",
            "assignment_prompt": f"1. {question}",
            "reference_answer": ref_answer,
            "dataset_name": "VALIDATION_FEEDBACK",
            "dataset_max_score": 5,
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
            df.at[idx, "model_name"] = LLM_MODE
            df.at[idx, "prompt_version"] = "v1"

        except Exception as e:
            print(f"[ERROR] sample {row['sample_id']}: {e}")
            df.at[idx, "ai_grade_multi"] = ""
            df.at[idx, "ai_feedback_multi"] = f"ERROR: {e}"
            df.at[idx, "ai_confidence_multi"] = ""
            df.at[idx, "model_name"] = LLM_MODE
            df.at[idx, "prompt_version"] = "v1"

        df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    print(f"[OK] wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
