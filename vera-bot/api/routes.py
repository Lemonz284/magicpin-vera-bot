import time
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from config import START_TIME, TEAM_NAME, CONTACT_EMAIL, LLM_MODEL
from state.store import global_store
from engine.decision import select_and_build_actions
from engine.conversation import handle_merchant_reply
from api.schemas import (
    HealthzResponse,
    MetadataResponse,
    ContextRequest,
    ContextAcceptedResponse,
    TickRequest,
    TickResponse,
    ReplyRequest,
    ReplyResponse,
)

logger = logging.getLogger("vera.api")
router = APIRouter(prefix="/v1", tags=["Vera Bot"])

VALID_SCOPES = {"category", "merchant", "customer", "trigger"}


@router.get("/healthz", response_model=HealthzResponse)
async def healthz():
    try:
        uptime = int(time.time() - START_TIME)
        counts = global_store.count_by_scope()
        return HealthzResponse(
            status="ok",
            uptime_seconds=uptime,
            contexts_loaded=counts
        )
    except Exception as e:
        logger.error(f"/healthz error: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": "error", "detail": str(e)}
        )


@router.get("/metadata", response_model=MetadataResponse)
async def metadata():
    try:
        return MetadataResponse(
            team_name=TEAM_NAME,
            team_members=["Builder"],
            model=LLM_MODEL,
            approach="hybrid rule-based decision engine + LLM composer",
            contact_email=CONTACT_EMAIL,
            version="1.0.0",
            submitted_at="2026-09-26T18:00:00Z"
        )
    except Exception as e:
        logger.error(f"/metadata error: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": str(e)}
        )


@router.post("/context")
async def context(req: ContextRequest):
    try:
        # Validate scope
        if req.scope not in VALID_SCOPES:
            logger.warning(f"Invalid scope '{req.scope}' for context_id='{req.context_id}'")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "accepted": False,
                    "reason": "invalid_scope",
                    "details": "scope must be one of: category, merchant, customer, trigger"
                }
            )

        accepted, current_version = global_store.push_context(
            scope=req.scope,
            context_id=req.context_id,
            version=req.version,
            payload=req.payload,
            delivered_at=req.delivered_at
        )

        if not accepted:
            logger.info(f"Rejected stale context ({req.scope}, {req.context_id}): incoming v{req.version} <= current v{current_version}")
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "accepted": False,
                    "reason": "stale_version",
                    "current_version": current_version
                }
            )

        logger.debug(f"Accepted context ({req.scope}, {req.context_id}) v{req.version}")
        return ContextAcceptedResponse(
            accepted=True,
            ack_id=f"ack_{req.context_id}_v{req.version}",
            stored_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
    except Exception as e:
        logger.error(f"/context error: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"accepted": False, "reason": "server_error", "details": str(e)}
        )


@router.post("/tick", response_model=TickResponse)
async def tick(req: TickRequest):
    try:
        actions = select_and_build_actions(
            store=global_store,
            available_triggers=req.available_triggers,
            now=req.now
        )
        logger.info(f"/tick processed {len(req.available_triggers)} triggers -> produced {len(actions)} actions")
        return TickResponse(actions=actions)
    except Exception as e:
        logger.error(f"/tick error: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"actions": [], "error": str(e)}
        )


@router.post("/reply", response_model=ReplyResponse, response_model_exclude_none=True)
async def reply(req: ReplyRequest):
    try:
        resp = handle_merchant_reply(
            store=global_store,
            req=req
        )
        logger.info(f"/reply conv={req.conversation_id} role={req.from_role} -> action={resp.action}")
        return resp
    except Exception as e:
        logger.error(f"/reply error: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"action": "end", "rationale": f"Internal error handled gracefully: {e}"}
        )


@router.post("/teardown")
async def teardown():
    try:
        global_store.clear()
        logger.info("All store state wiped via /teardown")
        return {"accepted": True, "message": "All state wiped successfully"}
    except Exception as e:
        logger.error(f"/teardown error: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"accepted": False, "detail": str(e)}
        )
