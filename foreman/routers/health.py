"""Health and readiness fastapi routers for the foreman app."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(
    prefix="/healthcheck",
    tags=["healthcheck"],
    responses={404: {"description": "Not found"}},
)


class HealthModel(BaseModel):
    """Response to health check requests.

    Attributes:
        healthy: Am I healthy?
    """

    healthy: bool = True


class ReadyModel(BaseModel):
    """Response to ready check requests.

    Attributes:
        ready: Am I ready?
        dependencies: A key-value map of dependencies and their readiness status.
    """

    ready: bool = True
    dependencies: dict[str, bool | None] = Field(default_factory=dict)


@router.get("/")
async def healthy_check() -> HealthModel:
    """Check to see if the service is healthy.

    Returns:
        (HealthModel): HealthModel
    """
    healthbody: HealthModel = HealthModel()
    return healthbody


@router.get("/ready")
async def ready_check() -> ReadyModel:
    """Check to see if the service is ready.

    Returns:
        ReadyModel
    """
    dependencies: dict[str, bool | None] = {}
    is_ready = all(bool(dependency) for dependency in dependencies.values())
    ready_model = ReadyModel(ready=is_ready, dependencies=dependencies)
    if not is_ready:
        raise HTTPException(status_code=503, detail=ready_model.model_dump())
    else:
        return ready_model
