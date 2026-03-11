from backend.app.db import engine
from backend.app.models import Base
from fastapi import FastAPI, HTTPException, APIRouter, Depends
from backend.app.config import LLM_MODE
from pydantic import BaseModel
from backend.app.db import SessionLocal, get_db
from backend.app.models import (
    Submission,
    SubmissionChunk,
    ChunkEmbedding,
    SimilarityResult,
    FeedbackResult,
    ConceptHistory,
    StudentProfile,
)
from backend.app.chunking import split_numbered_answers, clean_text_basic
from backend.app.embeddings import local_embedding, cosine_similarity, to_json, from_json
from backend.app.multi_agent import run_multi_agent
from backend.app.profile import pick_weak_concepts, calc_trend, summarize_feedback
from sqlalchemy.orm import Session
from typing import Optional
import json
import backend.app.multi_agent as ma

print("USING MULTI_AGENT FILE:", ma.__file__)

app = FastAPI(title="FYP Feedback Backend")
Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"message": "FYP backend running", "try": "/health or /docs"}


@app.get("/health")
def health():
    return {"status": "ok", "llm_mode": LLM_MODE}


class SubmissionIn(BaseModel):
    moodle_submission_id: int
    assignment_id: int
    course_id: int
    student_id: int
    assignment_title: Optional[str] = ""
    assignment_prompt: Optional[str] = ""
    raw_text: Optional[str] = ""
    cleaned_text: Optional[str] = ""


def _safe_json_loads(v):
    if not v:
        return []
    if isinstance(v, list):
        return v
    try:
        return json.loads(v)
    except Exception:
        return []


def _assignment_keyword_set(title: str, prompt: str) -> set[str]:
    text = f"{title or ''} {prompt or ''}".lower()
    words = set()
    for token in [
        "docker", "image", "container", "compose", "containerization",
        "kubernetes", "service", "clusterip", "nodeport", "networkpolicy",
        "pod", "deployment", "ingress", "loadbalancer",
    ]:
        if token in text:
            words.add(token)
    return words


def _filter_recent_concepts_for_assignment(rows, assignment_title: str, assignment_prompt: str):
    current_keys = _assignment_keyword_set(assignment_title, assignment_prompt)
    if not current_keys:
        return [r.concept_scores or {} for r in rows if r.concept_scores]

    filtered = []
    for r in rows:
        cs = r.concept_scores or {}
        if not isinstance(cs, dict):
            continue

        keep = {}
        for k, v in cs.items():
            lk = str(k).lower()
            if any(word in lk for word in current_keys):
                keep[k] = v

        if keep:
            filtered.append(keep)

    return filtered


@app.post("/ingest/submission")
def ingest_submission(data: SubmissionIn):
    db = SessionLocal()
    try:
        source_text = (data.cleaned_text or data.raw_text or "").strip()
        if not source_text:
            raise HTTPException(
                status_code=400,
                detail="raw_text or cleaned_text must be provided and not empty"
            )

        cleaned = clean_text_basic(source_text)

        existing = db.query(Submission).filter(
            Submission.moodle_submission_id == data.moodle_submission_id
        ).first()

        if existing:
            existing.raw_text = data.raw_text
            existing.cleaned_text = cleaned
            existing.assignment_id = data.assignment_id
            existing.course_id = data.course_id
            existing.student_id = data.student_id
            existing.assignment_title = data.assignment_title
            existing.assignment_prompt = data.assignment_prompt
            existing.status = "pending"
            existing.plagiarism_flag = False

            db.query(SubmissionChunk).filter(
                SubmissionChunk.submission_id == existing.id
            ).delete()

            chunks = split_numbered_answers(cleaned)
            print(f"DEBUG ingest submission={existing.id} chunks={[(q, len(t)) for q, t in chunks]}")
            for qno, chunk_text in chunks:
                cclean = clean_text_basic(chunk_text)
                db.add(SubmissionChunk(
                    submission_id=existing.id,
                    question_no=qno,
                    chunk_text=chunk_text,
                    cleaned_text=cclean
                ))

            db.commit()
            return {
                "status": "updated",
                "id": existing.id,
                "chunks_saved": len(chunks),
                "chunk_questions": [q for q, _ in chunks]
            }

        submission = Submission(
            moodle_submission_id=data.moodle_submission_id,
            assignment_id=data.assignment_id,
            course_id=data.course_id,
            student_id=data.student_id,
            assignment_title=data.assignment_title,
            assignment_prompt=data.assignment_prompt,
            raw_text=data.raw_text,
            cleaned_text=cleaned,
            status="pending",
            plagiarism_flag=False
        )
        db.add(submission)
        db.commit()
        db.refresh(submission)

        chunks = split_numbered_answers(cleaned)
        print(f"DEBUG ingest submission={submission.id} chunks={[(q, len(t)) for q, t in chunks]}")
        for qno, chunk_text in chunks:
            cclean = clean_text_basic(chunk_text)
            db.add(SubmissionChunk(
                submission_id=submission.id,
                question_no=qno,
                chunk_text=chunk_text,
                cleaned_text=cclean
            ))
        db.commit()

        return {
            "status": "stored",
            "id": submission.id,
            "chunks_saved": len(chunks),
            "chunk_questions": [q for q, _ in chunks]
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.post("/plagiarism/check/{submission_id}")
def plagiarism_check(submission_id: int, threshold: float = 0.93):
    db = SessionLocal()
    try:
        chunks = db.query(SubmissionChunk).filter(SubmissionChunk.submission_id == submission_id).all()
        if not chunks:
            raise HTTPException(status_code=404, detail="No chunks found for submission")

        sub = db.query(Submission).filter(Submission.id == submission_id).first()
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        for c in chunks:
            existing = db.query(ChunkEmbedding).filter(ChunkEmbedding.chunk_id == c.id).first()
            if not existing:
                vec = local_embedding(c.cleaned_text)
                db.add(ChunkEmbedding(chunk_id=c.id, embedding_json=to_json(vec)))
        db.commit()

        flags = []

        for c in chunks:
            if len((c.cleaned_text or "").split()) < 8:
                continue

            cemb = db.query(ChunkEmbedding).filter(ChunkEmbedding.chunk_id == c.id).first()
            if not cemb:
                continue

            v1 = from_json(cemb.embedding_json)

            others = (
                db.query(SubmissionChunk, ChunkEmbedding, Submission)
                .join(ChunkEmbedding, ChunkEmbedding.chunk_id == SubmissionChunk.id)
                .join(Submission, Submission.id == SubmissionChunk.submission_id)
                .filter(Submission.assignment_id == sub.assignment_id)
                .filter(SubmissionChunk.question_no == c.question_no)
                .filter(SubmissionChunk.id != c.id)
                .filter(Submission.student_id != sub.student_id)
                .all()
            )

            best = None
            for other_chunk, other_emb, other_sub in others:
                if len((other_chunk.cleaned_text or "").split()) < 8:
                    continue

                v2 = from_json(other_emb.embedding_json)
                sim = cosine_similarity(v1, v2)

                if best is None or sim > best["similarity"]:
                    best = {
                        "other_chunk_id": other_chunk.id,
                        "similarity": sim,
                        "other_submission_id": other_chunk.submission_id,
                        "other_student_id": other_sub.student_id,
                    }

            if best and best["similarity"] >= threshold:
                flags.append({
                    "chunk_id": c.id,
                    "question_no": c.question_no,
                    "matched_submission_id": best["other_submission_id"],
                    "matched_chunk_id": best["other_chunk_id"],
                    "matched_student_id": best["other_student_id"],
                    "similarity": round(best["similarity"], 4),
                })

                db.add(SimilarityResult(
                    chunk_id=c.id,
                    matched_chunk_id=best["other_chunk_id"],
                    similarity_score=str(best["similarity"]),
                    decision="flagged",
                    evidence_note=f"High similarity on Q{c.question_no} with submission {best['other_submission_id']}"
                ))

        sub.plagiarism_flag = len(flags) > 0
        sub.status = "flagged" if len(flags) > 0 else "pending"

        db.commit()
        return {
            "submission_id": submission_id,
            "threshold": threshold,
            "flags": flags,
            "flagged_count": len(flags)
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.post("/llm/multi_grade/{submission_id}")
def llm_multi_grade(submission_id: int):
    db = SessionLocal()
    try:
        sub = db.query(Submission).filter(Submission.id == submission_id).first()
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        chunks = db.query(SubmissionChunk).filter(SubmissionChunk.submission_id == submission_id).all()
        qmap = {c.question_no: c.cleaned_text for c in chunks}

        profile = db.query(StudentProfile).filter(StudentProfile.student_id == sub.student_id).first()

        recent_feedback_rows = (
            db.query(FeedbackResult)
            .join(Submission, FeedbackResult.submission_id == Submission.id)
            .filter(Submission.student_id == sub.student_id)
            .order_by(FeedbackResult.id.desc())
            .limit(5)
            .all()
        )

        recent_concept_rows = (
            db.query(ConceptHistory)
            .filter(ConceptHistory.student_id == sub.student_id)
            .order_by(ConceptHistory.id.desc())
            .limit(5)
            .all()
        )

        filtered_recent_concepts = _filter_recent_concepts_for_assignment(
            recent_concept_rows,
            sub.assignment_title or "",
            sub.assignment_prompt or "",
        )

        student_context = {
            "student_id": sub.student_id,
            "weak_concepts": _safe_json_loads(profile.weak_concepts) if profile else [],
            "trend": profile.trend if profile else "unknown",
            "last_feedback_summary": profile.last_feedback_summary if profile else "",
            "recent_grades": [
                float(x.grade) for x in recent_feedback_rows
                if x.grade not in (None, "")
            ],
            "recent_feedback_summaries": [
                summarize_feedback(x.feedback_text or "") for x in recent_feedback_rows[:3]
            ],
            "recent_concepts": filtered_recent_concepts,
            "plagiarism_flag": bool(sub.plagiarism_flag),
        }

        assignment_context = {
            "assignment_title": sub.assignment_title or f"Assignment {sub.assignment_id}",
            "assignment_prompt": sub.assignment_prompt or "",
        }

        result = run_multi_agent(qmap, student_context, assignment_context)

        print("DEBUG qmap:", qmap)
        print("DEBUG multi_agent result:", json.dumps(result, indent=2, ensure_ascii=False))

        feedback_text = (result.get("final_feedback") or "").strip()
        if sub.plagiarism_flag and not feedback_text.lower().startswith("⚠️ plagiarism warning".lower()):
            feedback_text = "⚠️ Plagiarism warning: Similarity flagged.\n\n" + feedback_text

        cs = result.get("concept_scores", {}) or {}

        db.add(ConceptHistory(
            student_id=sub.student_id,
            submission_id=submission_id,
            concept_scores=cs,
            assignment_title=sub.assignment_title or ""
        ))

        new_grade = float(result.get("grade", 0))
        weak = pick_weak_concepts({k: float(v) for k, v in cs.items()}, top_k=3) if cs else []
        summary = summarize_feedback(result.get("final_feedback", ""))

        concept_mastery = {}
        if profile and isinstance(profile.concept_mastery_json, dict):
            concept_mastery = dict(profile.concept_mastery_json)

        for k, v in cs.items():
            prev = concept_mastery.get(k)
            if isinstance(prev, (int, float)):
                concept_mastery[k] = round((prev * 0.7) + (float(v) * 0.3), 2)
            else:
                concept_mastery[k] = round(float(v), 2)

        if profile is None:
            profile = StudentProfile(
                student_id=sub.student_id,
                weak_concepts=json.dumps(weak),
                last_feedback_summary=summary,
                last_grade=str(new_grade),
                trend="unknown",
                concept_mastery_json=concept_mastery,
            )
            db.add(profile)
        else:
            prev_grade = float(profile.last_grade) if profile.last_grade else None
            profile.trend = calc_trend(prev_grade, new_grade)
            profile.weak_concepts = json.dumps(weak)
            profile.last_feedback_summary = summary
            profile.last_grade = str(new_grade)
            profile.concept_mastery_json = concept_mastery

        fr = FeedbackResult(
            submission_id=submission_id,
            grade=str(result.get("grade", "")),
            feedback_text=feedback_text,
            feedback_json=result,
            confidence=str(result.get("confidence", "")),
        )
        db.add(fr)
        sub.status = "graded"
        db.commit()
        db.refresh(fr)

        return {
            "status": "graded",
            "submission_id": submission_id,
            "feedback_id": fr.id,
            "multi_agent": result
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.get("/students/{student_id}/progress")
def student_progress(student_id: int, limit: int = 20):
    db = SessionLocal()
    try:
        profile = db.query(StudentProfile).filter(StudentProfile.student_id == student_id).first()

        rows = (
            db.query(ConceptHistory)
              .filter(ConceptHistory.student_id == student_id)
              .order_by(ConceptHistory.id.desc())
              .limit(limit)
              .all()
        )

        concept_history = [
            {
                "submission_id": r.submission_id,
                "assignment_title": r.assignment_title,
                "concept_scores": r.concept_scores or {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

        grades = (
            db.query(FeedbackResult)
              .join(Submission, FeedbackResult.submission_id == Submission.id)
              .filter(Submission.student_id == student_id)
              .order_by(FeedbackResult.id.desc())
              .limit(limit)
              .all()
        )

        grade_history = [
            {
                "submission_id": g.submission_id,
                "grade": float(g.grade) if g.grade else None,
                "confidence": float(g.confidence) if g.confidence else None,
                "created_at": g.created_at.isoformat() if g.created_at else None,
            }
            for g in grades
        ]

        return {
            "student_id": student_id,
            "profile": {
                "weak_concepts": _safe_json_loads(profile.weak_concepts) if profile else [],
                "trend": profile.trend if profile else "unknown",
                "last_grade": float(profile.last_grade) if profile and profile.last_grade else None,
                "last_feedback_summary": profile.last_feedback_summary if profile else "",
                "concept_mastery_json": profile.concept_mastery_json if profile else {},
            },
            "grade_history": grade_history,
            "concept_history": concept_history
        }

    finally:
        db.close()


@app.get("/moodle/push_payload/{submission_id}")
def moodle_push_payload(submission_id: int):
    db = SessionLocal()
    try:
        sub = db.query(Submission).filter(Submission.id == submission_id).first()
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        fb = (
            db.query(FeedbackResult)
              .filter(FeedbackResult.submission_id == submission_id)
              .order_by(FeedbackResult.id.desc())
              .first()
        )
        if not fb:
            raise HTTPException(status_code=404, detail="No feedback found for submission")

        return {
            "moodle_user_id": int(sub.student_id),
            "moodle_submission_id": int(sub.moodle_submission_id) if sub.moodle_submission_id else None,
            "moodle_assign_id": int(sub.assignment_id),
            "grade": float(fb.grade) if fb.grade else None,
            "feedback_text": fb.feedback_text or ""
        }
    finally:
        db.close()


router = APIRouter(prefix="/submission", tags=["submission"])
app.include_router(router)


@router.get("/by_moodle/{moodle_submission_id}")
def get_by_moodle_id(moodle_submission_id: int, db: Session = Depends(get_db)):
    sub = db.query(Submission).filter(Submission.moodle_submission_id == moodle_submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "id": sub.id,
        "moodle_submission_id": sub.moodle_submission_id,
        "student_id": sub.student_id,
        "assignment_id": sub.assignment_id,
        "course_id": sub.course_id,
        "assignment_title": sub.assignment_title,
        "status": getattr(sub, "status", None),
        "plagiarism_flag": getattr(sub, "plagiarism_flag", None),
    }