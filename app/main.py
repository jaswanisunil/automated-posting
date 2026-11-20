from fastapi import Depends, FastAPI

from app.dependencies import get_posting_service
from app.schemas import PostingRequest, PostingResponse
from app.services.posting_service import PostingService


app = FastAPI(title="Automated Multi-Platform Posting API", version="0.1.0")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/posting", response_model=PostingResponse)
async def post_message(
    request: PostingRequest,
    posting_service: PostingService = Depends(get_posting_service),
) -> PostingResponse:
    results = await posting_service.post_message(request.message)
    return PostingResponse(
        success=any(result.status == "success" for result in results),
        results=results,
    )
