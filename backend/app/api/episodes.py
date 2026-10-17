from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import CareEpisode, Patient, Doctor
from app.schemas.episode import EpisodeCreate, EpisodeResponse
from app.api.auth import get_current_user
router = APIRouter(prefix="/api/episodes", tags=["Care Episodes"], dependencies=[Depends(get_current_user)])
def next_episode_ref(db: Session) -> str:
    count = db.scalar(select(func.count()).select_from(CareEpisode)) or 0
    return f"EP-{count + 1:06d}"
@router.post("", response_model=EpisodeResponse, status_code=201)
def create_episode(payload: EpisodeCreate, db: Session = Depends(get_db)):
    if not db.get(Patient, payload.patient_id): raise HTTPException(status_code=404, detail="Patient not found")
    data = payload.model_dump()
    if payload.doctor_id:
        doctor = db.get(Doctor, payload.doctor_id)
        if not doctor or not doctor.is_active:
            raise HTTPException(status_code=422, detail="Selected doctor does not exist or is inactive.")
        if doctor.department != payload.department:
            raise HTTPException(status_code=422, detail="Selected doctor does not belong to the selected department.")
        data["treating_doctor"] = doctor.full_name
    episode = CareEpisode(episode_ref=next_episode_ref(db), **data)
    db.add(episode); db.commit(); db.refresh(episode); return episode
@router.get("", response_model=list[EpisodeResponse])
def list_episodes(patient_id: UUID | None = None, db: Session = Depends(get_db)):
    query = select(CareEpisode).order_by(CareEpisode.created_at.desc())
    if patient_id: query = query.where(CareEpisode.patient_id == patient_id)
    return list(db.scalars(query).all())
