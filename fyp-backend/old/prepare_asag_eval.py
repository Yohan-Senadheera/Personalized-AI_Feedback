import pandas as pd

INPUT_FILE = "asag_dataset.csv"
OUTPUT_FILE = "evaluation_asag.csv"

def main():
    df = pd.read_csv(INPUT_FILE)

    # Keep only rows with required fields
    df = df.dropna(subset=["question", "student_answer", "ref_answer", "grades_round"]).copy()

    # ASAG grades are 0,1,2 -> convert to 0,50,100
    df["teacher_grade_raw"] = df["grades_round"].astype(float)
    df["teacher_grade"] = (df["teacher_grade_raw"] / 2.0) * 100.0

    # Optional: keep dataset manageable
    # Start with 80 samples for fast evaluation
    df = df.sample(n=min(80, len(df)), random_state=42).reset_index(drop=True)

    out = pd.DataFrame({
        "sample_id": range(1, len(df) + 1),
        "question_id": df.get("question_id", ""),
        "assignment": df["question"].astype(str),
        "reference_answer": df["ref_answer"].astype(str),
        "student_answer": df["student_answer"].astype(str),
        "teacher_grade_raw": df["teacher_grade_raw"],
        "teacher_grade": df["teacher_grade"],
        "ai_grade_multi": "",
        "ai_feedback_multi": "",
        "ai_confidence_multi": "",
        "baseline_grade": "",
        "baseline_feedback": "",
    })

    out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
    print(f"[OK] wrote {OUTPUT_FILE} with {len(out)} rows")

if __name__ == "__main__":
    main()