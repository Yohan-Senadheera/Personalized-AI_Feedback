import pandas as pd

INPUT_FILE = "validation.csv"
OUTPUT_FILE = "evaluation_validation.csv"


def main():
    df = pd.read_csv(INPUT_FILE)

    df = df.dropna(subset=[
        "id",
        "question",
        "reference_answer",
        "provided_answer",
        "answer_feedback",
        "score",
    ]).copy()

    df["sample_id"] = range(1, len(df) + 1)
    df["teacher_grade"] = pd.to_numeric(df["score"], errors="coerce")
    df["teacher_feedback"] = df["answer_feedback"].astype(str)

    out = pd.DataFrame({
        "sample_id": df["sample_id"],
        "dataset_id": df["id"],
        "assignment": df["question"].astype(str),
        "reference_answer": df["reference_answer"].astype(str),
        "student_answer": df["provided_answer"].astype(str),
        "teacher_grade": df["teacher_grade"],
        "teacher_feedback": df["teacher_feedback"],
        "ai_grade_multi": "",
        "ai_feedback_multi": "",
        "ai_confidence_multi": "",
        "model_name": "",
        "prompt_version": "v1",
    })

    out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
    print(f"[OK] wrote {OUTPUT_FILE} with {len(out)} rows")


if __name__ == "__main__":
    main()
