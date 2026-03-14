import csv
from pathlib import Path

from sqlalchemy import func, and_

from backend.app.db import SessionLocal
from backend.app.models import Submission, FeedbackResult


OUT_FILE = Path("evaluation_dataset.csv")


def main():
    db = SessionLocal()
    try:
        # latest feedback row per submission
        latest_feedback_subq = (
            db.query(
                FeedbackResult.submission_id.label("submission_id"),
                func.max(FeedbackResult.id).label("latest_feedback_id"),
            )
            .group_by(FeedbackResult.submission_id)
            .subquery()
        )

        rows = (
            db.query(Submission, FeedbackResult)
            .outerjoin(
                latest_feedback_subq,
                Submission.id == latest_feedback_subq.c.submission_id
            )
            .outerjoin(
                FeedbackResult,
                and_(
                    FeedbackResult.id == latest_feedback_subq.c.latest_feedback_id,
                    FeedbackResult.submission_id == Submission.id,
                )
            )
            .order_by(Submission.assignment_id.asc(), Submission.student_id.asc())
            .all()
        )

        with OUT_FILE.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "submission_id",
                    "moodle_submission_id",
                    "student_id",
                    "assignment_id",
                    "assignment_title",
                    "student_answer",
                    "ai_grade_multi",
                    "ai_feedback_multi",
                    "ai_confidence_multi",
                    "plagiarism_flag",
                    "teacher_grade",
                    "teacher_feedback",
                    "baseline_grade",
                    "baseline_feedback",
                ],
            )
            writer.writeheader()

            for sub, fb in rows:
                writer.writerow(
                    {
                        "submission_id": sub.id,
                        "moodle_submission_id": sub.moodle_submission_id,
                        "student_id": sub.student_id,
                        "assignment_id": sub.assignment_id,
                        "assignment_title": sub.assignment_title or "",
                        "student_answer": (sub.cleaned_text or sub.raw_text or "").strip(),
                        "ai_grade_multi": fb.grade if fb and fb.grade is not None else "",
                        "ai_feedback_multi": fb.feedback_text if fb and fb.feedback_text else "",
                        "ai_confidence_multi": fb.confidence if fb and fb.confidence else "",
                        "plagiarism_flag": sub.plagiarism_flag,
                        "teacher_grade": "",
                        "teacher_feedback": "",
                        "baseline_grade": "",
                        "baseline_feedback": "",
                    }
                )

        print(f"[OK] wrote {OUT_FILE.resolve()}")
        print(f"[OK] exported {len(rows)} rows")

    finally:
        db.close()


if __name__ == "__main__":
    main()