from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Task, TaskSubmission, User
from app.services.points import apply_points


def submit_task(db: Session, *, user_id: str, task_id: str, evidence: str | None = None) -> TaskSubmission:
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None or user.status != "active":
        raise ValueError("account is not active")
    task = db.scalar(select(Task).where(Task.id == task_id))
    if task is None or task.status != "active":
        raise ValueError("task is unavailable")
    submission = TaskSubmission(
        user_id=user_id,
        task_id=task_id,
        status="pending",
        evidence=evidence,
    )
    db.add(submission)
    db.flush()
    return submission


def review_task(
    db: Session,
    *,
    submission_id: str,
    approved: bool,
    reviewer_id: str,
    now: datetime | None = None,
) -> TaskSubmission:
    submission = db.scalar(
        select(TaskSubmission).where(TaskSubmission.id == submission_id).with_for_update()
    )
    if submission is None:
        raise ValueError("submission not found")
    if submission.status != "pending":
        raise ValueError("submission has already been reviewed")
    current = now or datetime.now(timezone.utc)

    if approved:
        task = db.scalar(select(Task).where(Task.id == submission.task_id).with_for_update())
        if task is None:
            raise ValueError("task not found")
        apply_points(
            db,
            user_id=submission.user_id,
            amount=task.reward_points,
            event_type="task_reward",
            idempotency_key=f"task:{submission.id}",
            reference_id=submission.id,
        )
        submission.status = "approved"
    else:
        submission.status = "rejected"
    submission.verified_at = current
    db.add(submission)
    db.flush()
    return submission
