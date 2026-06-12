"""Authenticated internal API for the agent workflow."""


from fastapi import APIRouter, Depends, HTTPException, Request

from shared.utils.logger import get_logger
from shared.utils.network import UnsafeTargetError, validate_public_http_url_async
from shared.utils.security import require_internal_service_token
from src.models import AgentResponse, AgentRunRequest, HumanFeedbackRequest

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(require_internal_service_token)])


@router.post("/run", response_model=AgentResponse)
async def run_agent(req: AgentRunRequest, request: Request):
    """Run or retry the custom crawler workflow."""
    logger.info("Agent run requested: request_id=%s url=%s", req.request_id, req.url)
    try:
        await validate_public_http_url_async(req.url)
    except UnsafeTargetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    graph = request.app.state.agent_graph
    result = await graph.run(
        request_id=req.request_id,
        url=req.url,
        data_type=req.data_type,
        required_fields=req.required_fields,
        max_pages=req.max_pages,
        max_records=req.max_records,
        rate_limit_rps=req.rate_limit_rps,
        timeout_seconds=req.timeout_seconds,
        respect_robots_txt=req.respect_robots_txt,
        initial_analysis=req.initial_analysis,
        template_failure=req.template_failure,
    )
    return AgentResponse(
        status=result.get("status", "failed"),
        records=result.get("records", []),
        record_count=len(result.get("records", [])),
        crawler_code=result.get("crawler_code"),
        artifact_path=result.get("artifact_path"),
        attempts=result.get("attempts", 0),
        analysis=result.get("analysis"),
        test_result=result.get("test_result"),
        errors=result.get("errors", []),
    )


@router.get("/runs/{request_id}")
async def get_run_state(request_id: str, request: Request):
    """Inspect the latest durable state for a request."""
    state = await request.app.state.agent_graph.get_state(request_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Agent run {request_id} not found")
    state.pop("crawler_code", None)
    return state


@router.post("/feedback", status_code=202)
async def submit_feedback(payload: HumanFeedbackRequest, request: Request):
    """Persist expert feedback for use by future runs."""
    await request.app.state.memory_manager.save_human_feedback(
        payload.domain,
        payload.feedback,
        payload.feedback_type,
        payload.metadata,
    )
    return {"status": "accepted", "domain": payload.domain}
