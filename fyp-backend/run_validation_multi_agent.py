import os
import sys
import pandas as pd
from tqdm import tqdm
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
sys.path.append(os.getcwd())

from backend.app.multi_agent import run_multi_agent
from backend.app.config import LLM_MODE

INPUT_FILE = "evaluation_validation.csv"
OUTPUT_FILE = f"evaluation_validation_{LLM_MODE}.csv"

# Safe default for OpenAI. You can increase for Groq later.
MAX_WORKERS = 5
SAVE_EVERY = 10


def safe_text(x):
    if pd.isna(x):
        return ""
    return str(x).strip()


def process_row(row):
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
        "dataset_max_score": 7,
        "dataset_grade_max": 3.5,
    }

    student_context = {
        "weak_concepts": [],
        "trend": "unknown",
        "recent_grades": [],
        "recent_feedback_summaries": [],
        "recent_concepts": [],
        "plagiarism_flag": False,
    }

    result = run_multi_agent(
        qmap=qmap,
        student_context=student_context,
        assignment_context=assignment_context,
    )

    return {
        "grade": result.get("grade", ""),
        "feedback": result.get("final_feedback", ""),
        "confidence": result.get("confidence", ""),
    }


def main():
    if os.path.exists(OUTPUT_FILE):
        df = pd.read_csv(OUTPUT_FILE)
        print(f"[RESUME] loaded existing {OUTPUT_FILE}")
    else:
        df = pd.read_csv(INPUT_FILE)

    target_cols = [
        "ai_grade_multi",
        "ai_feedback_multi",
        "ai_confidence_multi",
        "model_name",
        "prompt_version",
    ]

    for col in target_cols:
        if col not in df.columns:
            df[col] = ""

    for col in target_cols:
        df[col] = df[col].astype("object")

    pending = []
    for idx, row in df.iterrows():
        existing_grade = str(row.get("ai_grade_multi", "")).strip()
        if existing_grade not in ("", "nan", "None"):
            continue
        pending.append((idx, row))

    print(f"[INFO] pending rows: {len(pending)} / {len(df)}")
    if not pending:
        print(f"[OK] nothing to do, {OUTPUT_FILE} already complete")
        return

    completed_since_save = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_row, row): idx
            for idx, row in pending
        }

        for future in tqdm(as_completed(futures), total=len(futures), desc=f"Validation grading ({LLM_MODE})"):
            idx = futures[future]

            try:
                result = future.result()
                df.at[idx, "ai_grade_multi"] = str(result.get("grade", ""))
                df.at[idx, "ai_feedback_multi"] = str(result.get("feedback", ""))
                df.at[idx, "ai_confidence_multi"] = str(result.get("confidence", ""))
                df.at[idx, "model_name"] = str(LLM_MODE)
                df.at[idx, "prompt_version"] = "v1"

            except Exception as e:
                print(f"[ERROR] row {idx}: {e}")
                df.at[idx, "ai_grade_multi"] = ""
                df.at[idx, "ai_feedback_multi"] = f"ERROR: {e}"
                df.at[idx, "ai_confidence_multi"] = ""
                df.at[idx, "model_name"] = str(LLM_MODE)
                df.at[idx, "prompt_version"] = "v1"

            completed_since_save += 1
            if completed_since_save >= SAVE_EVERY:
                df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
                completed_since_save = 0

    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
    print(f"[OK] wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
