from backend.app.db import engine
from backend.app.models import Base
from fastapi import FastAPI
from backend.app.config import LLM_MODE
from fastapi import HTTPException
from pydantic import BaseModel
from backend.app.db import SessionLocal
from backend.app.models import Submission
from backend.app.models import Submission, SubmissionChunk
from backend.app.chunking import split_numbered_answers, clean_text_basic
from backend.app.models import SubmissionChunk, ChunkEmbedding
from backend.app.embeddings import mock_embedding, cosine_similarity, to_json, from_json
from backend.app.embeddings import local_embedding, cosine_similarity, to_json, from_json
from typing import Optional
from pydantic import BaseModel
from backend.app.models import SimilarityResult
from backend.app.models import Submission, SubmissionChunk, FeedbackResult
from backend.app.grading import grade_networking_short_answer
from backend.app.llm import get_llm
from backend.app.multi_agent import run_multi_agent
import json
from backend.app.models import ConceptHistory, StudentProfile
from backend.app.profile import pick_weak_concepts, calc_trend, summarize_feedback

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
    raw_text: Optional[str] = ""
    cleaned_text: Optional[str] = ""


@app.post("/ingest/submission")
def ingest_submission(data: SubmissionIn):
    db = SessionLocal()
    try:
        source_text = data.cleaned_text or data.raw_text

        if not source_text or not source_text.strip():
            raise HTTPException(
                status_code=400,
                detail="raw_text or cleaned_text must be provided and not empty"
            )

        cleaned = clean_text_basic(source_text)

        submission = Submission(
            moodle_submission_id=data.moodle_submission_id,
            assignment_id=data.assignment_id,
            course_id=data.course_id,
            student_id=data.student_id,
            raw_text=data.raw_text,
            cleaned_text=cleaned,
        )
        db.add(submission)
        db.commit()
        db.refresh(submission)

        # Split into chunks (Q1/Q2/Q3)
        chunks = split_numbered_answers(cleaned)

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
def plagiarism_check(submission_id: int, threshold: float = 0.90):
    db = SessionLocal()
    try:
        # 1) get chunks of this submission
        chunks = db.query(SubmissionChunk).filter(SubmissionChunk.submission_id == submission_id).all()
        if not chunks:
            raise HTTPException(status_code=404, detail="No chunks found for submission")

        # 2) create embeddings for these chunks if not exist
        for c in chunks:
            existing = db.query(ChunkEmbedding).filter(ChunkEmbedding.chunk_id == c.id).first()
            if not existing:
                vec = local_embedding(c.cleaned_text)
                db.add(ChunkEmbedding(chunk_id=c.id, embedding_json=to_json(vec)))
        db.commit()

        # 3) compare each chunk to other chunks in same assignment (for now: compare all chunks in DB)
        # Later we will restrict: same assignment_id, same question_no, same course.
        flags = []
        for c in chunks:
            cemb = db.query(ChunkEmbedding).filter(ChunkEmbedding.chunk_id == c.id).first()
            v1 = from_json(cemb.embedding_json)

            # compare with all other chunks of same question_no (excluding itself)
            others = (
                db.query(SubmissionChunk, ChunkEmbedding)
                  .join(ChunkEmbedding, ChunkEmbedding.chunk_id == SubmissionChunk.id)
                  .filter(SubmissionChunk.question_no == c.question_no)
                  .filter(SubmissionChunk.id != c.id)
                  .all()
            )

            best = None
            for other_chunk, other_emb in others:
                v2 = from_json(other_emb.embedding_json)
                sim = cosine_similarity(v1, v2)
                if best is None or sim > best["similarity"]:
                    best = {"other_chunk_id": other_chunk.id, "similarity": sim, "other_submission_id": other_chunk.submission_id}

            if best and best["similarity"] >= threshold:
                flags.append({
                    "chunk_id": c.id,
                    "question_no": c.question_no,
                    "matched_submission_id": best["other_submission_id"],
                    "matched_chunk_id": best["other_chunk_id"],
                    "similarity": round(best["similarity"], 4)
                })

                # ✅ store in DB
                db.add(SimilarityResult(
                    chunk_id=c.id,
                    matched_chunk_id=best["other_chunk_id"],
                    similarity_score=str(best["similarity"]),
                    decision="flagged",
                    evidence_note=f"High similarity on Q{c.question_no} with submission {best['other_submission_id']}"
                ))

                # ✅ update submission status if flagged
                from backend.app.models import Submission
                sub = db.query(Submission).filter(Submission.id == submission_id).first()
                if sub:
                    if len(flags) > 0:
                        sub.plagiarism_flag = True
                        sub.status = "flagged"
                    else:
                        sub.plagiarism_flag = False
                        if sub.status == "flagged":
                            sub.status = "pending"
                db.commit()

        return {"submission_id": submission_id, "threshold": threshold, "flags": flags, "flagged_count": len(flags)}

    finally:
        db.close()


@app.post("/grade/{submission_id}")
def grade_submission(submission_id: int, max_grade: float = 100.0):
    db = SessionLocal()
    try:
        sub = db.query(Submission).filter(Submission.id == submission_id).first()
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        chunks = db.query(SubmissionChunk).filter(SubmissionChunk.submission_id == submission_id).all()
        qmap = {c.question_no: c.cleaned_text for c in chunks}

        grade, feedback_text, feedback_json = grade_networking_short_answer(qmap, max_grade=max_grade)

        # If plagiarism flagged, add warning
        if sub.plagiarism_flag:
            feedback_text = "⚠️ Plagiarism warning: This submission is highly similar to another submission on at least one question.\n\n" + feedback_text

        # store result
        fr = FeedbackResult(
            submission_id=submission_id,
            grade=str(grade),
            feedback_text=feedback_text,
            feedback_json=feedback_json,
            confidence="0.75"
        )
        db.add(fr)

        # update submission status
        sub.status = "graded"
        db.commit()
        db.refresh(fr)

        return {"status": "graded", "submission_id": submission_id, "grade": grade, "feedback_id": fr.id}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        db.close()


@app.post("/llm/grade/{submission_id}")
def llm_grade_submission(submission_id: int):
    db = SessionLocal()
    try:
        sub = db.query(Submission).filter(Submission.id == submission_id).first()
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")

        chunks = db.query(SubmissionChunk).filter(SubmissionChunk.submission_id == submission_id).all()
        qmap = {c.question_no: c.cleaned_text for c in chunks}

        llm = get_llm()

        system = "You are an academic assistant that grades short answers and returns STRICT JSON."
        user = f"""
            Assignment: Kubernetes basics (Services, ClusterIP vs NodePort, NetworkPolicy).
            Student answers:
            Q1: {qmap.get(1,"")}
            Q2: {qmap.get(2,"")}
            Q3: {qmap.get(3,"")}

            Return JSON with fields:
            grade (0-100), confidence (0-1),
            strengths (list), weaknesses (list), misconceptions (list),
            next_steps (list),
            concept_scores (object with keys: service, clusterip_nodeport, networkpolicy each 0-1)
            """

        result = llm.generate_json(system=system, user=user)

        feedback_text = (
            "LLM Feedback:\n"
            f"Grade: {result.get('grade')}\n\n"
            "Strengths:\n- " + "\n- ".join(result.get("strengths", [])) + "\n\n"
            "Weaknesses:\n- " + "\n- ".join(result.get("weaknesses", [])) + "\n\n"
            "Next steps:\n- " + "\n- ".join(result.get("next_steps", []))
        )

        if sub.plagiarism_flag:
            feedback_text = "⚠️ Plagiarism warning: Similarity flagged.\n\n" + feedback_text

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

        return {"status": "graded", "submission_id": submission_id, "feedback_id": fr.id, "llm_result": result}

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
        student_context = {
            "student_id": sub.student_id,
            "weak_concepts": json.loads(profile.weak_concepts) if profile and profile.weak_concepts else [],
            "trend": profile.trend if profile else "unknown",
            "last_feedback_summary": profile.last_feedback_summary if profile else ""
        }

        result = run_multi_agent(qmap, student_context)

        feedback_text = result.get("final_feedback", "")
        if sub.plagiarism_flag:
            feedback_text = "⚠️ Plagiarism warning: Similarity flagged.\n\n" + feedback_text


                # --- Save concept history ---
        cs = result.get("concept_scores", {})
        service = str(cs.get("service", ""))
        clusterip_nodeport = str(cs.get("clusterip_nodeport", ""))
        networkpolicy = str(cs.get("networkpolicy", ""))

        db.add(ConceptHistory(
            student_id=sub.student_id,
            submission_id=submission_id,
            service=service,
            clusterip_nodeport=clusterip_nodeport,
            networkpolicy=networkpolicy
        ))

        # --- Update student profile ---
        profile = db.query(StudentProfile).filter(StudentProfile.student_id == sub.student_id).first()

        new_grade = float(result.get("grade", 0))

        weak = pick_weak_concepts({
            "service": float(cs.get("service", 0)),
            "clusterip_nodeport": float(cs.get("clusterip_nodeport", 0)),
            "networkpolicy": float(cs.get("networkpolicy", 0)),
        }, top_k=2)

        summary = summarize_feedback(result.get("final_feedback", ""))

        if profile is None:
            profile = StudentProfile(
                student_id=sub.student_id,
                weak_concepts=json.dumps(weak),
                last_feedback_summary=summary,
                last_grade=str(new_grade),
                trend="unknown"
            )
            db.add(profile)
        else:
            prev = float(profile.last_grade) if profile.last_grade else None
            profile.trend = calc_trend(prev, new_grade)
            profile.weak_concepts = json.dumps(weak)
            profile.last_feedback_summary = summary
            profile.last_grade = str(new_grade)

                
        
        
        
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

        return {"status": "graded", "submission_id": submission_id, "feedback_id": fr.id, "multi_agent": result}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.get("/students/{student_id}/progress")
def student_progress(student_id: int, limit: int = 20):
    db = SessionLocal()
    try:
        # profile
        profile = db.query(StudentProfile).filter(StudentProfile.student_id == student_id).first()

        # concept history (latest first)
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
                "service": float(r.service) if r.service else None,
                "clusterip_nodeport": float(r.clusterip_nodeport) if r.clusterip_nodeport else None,
                "networkpolicy": float(r.networkpolicy) if r.networkpolicy else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

        # grades (latest first) from feedback_results
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
                "weak_concepts": json.loads(profile.weak_concepts) if profile and profile.weak_concepts else [],
                "trend": profile.trend if profile else "unknown",
                "last_grade": float(profile.last_grade) if profile and profile.last_grade else None,
                "last_feedback_summary": profile.last_feedback_summary if profile else ""
            },
            "grade_history": grade_history,
            "concept_history": concept_history
        }

    finally:
        db.close()
