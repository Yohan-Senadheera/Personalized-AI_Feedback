from sqlalchemy import Column, Integer, BigInteger, Text, String, Boolean, DateTime
from sqlalchemy import UniqueConstraint, ForeignKey
from sqlalchemy.sql import func
from backend.app.db import Base
from sqlalchemy import Float, JSON

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    moodle_submission_id = Column(BigInteger)
    assignment_id = Column(BigInteger, nullable=False)
    course_id = Column(BigInteger, nullable=False)
    student_id = Column(BigInteger, nullable=False)

    raw_text = Column(Text)
    cleaned_text = Column(Text)

    status = Column(String, default="pending")
    plagiarism_flag = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    
class SubmissionChunk(Base):
    __tablename__ = "submission_chunks"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)

    question_no = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    cleaned_text = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("submission_id", "question_no", name="uq_submission_question"),
    )
    

class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    id = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(Integer, ForeignKey("submission_chunks.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Store embedding as TEXT for now (simple). Later we upgrade to pgvector type.
    embedding_json = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    
class SimilarityResult(Base):
    __tablename__ = "similarity_results"

    id = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(Integer, ForeignKey("submission_chunks.id", ondelete="CASCADE"), nullable=False)
    matched_chunk_id = Column(Integer, ForeignKey("submission_chunks.id", ondelete="CASCADE"), nullable=False)

    similarity_score = Column(Text, nullable=False)  # keep simple; store as text/decimal later
    decision = Column(String, default="ok")          # ok / flagged / review
    evidence_note = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FeedbackResult(Base):
    __tablename__ = "feedback_results"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)

    grade = Column(Text)
    feedback_text = Column(Text)
    feedback_json = Column(JSON, nullable=True)

    confidence = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ConceptHistory(Base):
    __tablename__ = "concept_history"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(BigInteger, nullable=False)
    submission_id = Column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)

    service = Column(Text)
    clusterip_nodeport = Column(Text)
    networkpolicy = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class StudentProfile(Base):
    __tablename__ = "student_profile"

    student_id = Column(BigInteger, primary_key=True, index=True)
    weak_concepts = Column(Text, default="[]")   # store JSON string for now
    last_feedback_summary = Column(Text)
    last_grade = Column(Text)
    trend = Column(String, default="unknown")
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
