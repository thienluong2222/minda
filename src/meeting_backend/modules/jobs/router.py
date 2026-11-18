from fastapi import APIRouter, Depends

from meeting_backend.api.dependencies import current_user, database
from meeting_backend.modules.jobs import service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(user=Depends(current_user), mongo=Depends(database)):
    return [
        service.job_view(j)
        for j in mongo.db.jobs.find({"owner_id": user["_id"]}).sort("created_at", -1).limit(100)
    ]


@router.get("/{job_id}")
def get_job(job_id: str, user=Depends(current_user), mongo=Depends(database)):
    return service.job_view(service.owned_job(mongo, user, job_id))


@router.post("/{job_id}/cancel")
def cancel(job_id: str, user=Depends(current_user), mongo=Depends(database)):
    return service.cancel(mongo, user, job_id)


@router.post("/{job_id}/retry", status_code=202)
def retry(job_id: str, user=Depends(current_user), mongo=Depends(database)):
    return service.retry(mongo, user, job_id)
