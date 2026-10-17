from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import CareEpisode, CareTask
from app.schemas.task import ALLOWED_TASK_TYPES, TaskCreate, TaskResponse
from app.api.auth import get_current_user
router = APIRouter(prefix="/api/tasks", tags=["Care Tasks"], dependencies=[Depends(get_current_user)])
@router.post("", response_model=TaskResponse, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    if payload.task_type not in ALLOWED_TASK_TYPES: raise HTTPException(status_code=422, detail=f"task_type must be one of {sorted(ALLOWED_TASK_TYPES)}")
    episode = db.get(CareEpisode, payload.episode_id)
    if not episode: raise HTTPException(status_code=404, detail="Care episode not found")
    if payload.start_date < episode.care_start_date or payload.end_date > episode.care_end_date:
        raise HTTPException(status_code=422, detail="Task dates must be within the care episode dates")
    task = CareTask(**payload.model_dump(), scheduled_date=payload.start_date, scheduled_time=None, repeat_daily=True)
    db.add(task); db.commit(); db.refresh(task); return task
@router.get("", response_model=list[TaskResponse])
def list_tasks(episode_id: UUID | None = None, scheduled_date: date | None = None, db: Session = Depends(get_db)):
    query = select(CareTask).order_by(CareTask.start_date, CareTask.title)
    if episode_id: query = query.where(CareTask.episode_id == episode_id)
    if scheduled_date: query = query.where(CareTask.start_date <= scheduled_date, CareTask.end_date >= scheduled_date)
    return list(db.scalars(query).all())
