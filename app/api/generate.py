from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.generation import generate

router = APIRouter()


class GenerateIn(BaseModel):
    user_id: int
    model_slug: str
    prompt: str
    ref_images: list[str] = Field(default_factory=list)


@router.post("/generate")
async def generate_endpoint(body: GenerateIn):
    task_id = await generate(body.user_id, body.model_slug, body.prompt, body.ref_images)
    return {"task_id": task_id}