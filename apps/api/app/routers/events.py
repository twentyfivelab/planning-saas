"""Flux temps réel (Server-Sent Events) : chaque modification validée d'un autre manager est annoncée en moins d'une seconde."""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from .. import models as m
from ..config import settings
from ..db import tenant_session
from ..deps import _session_row
from ..rbac import has_permission
from ..realtime import channel

router = APIRouter(tags=["temps réel"])
HEARTBEAT_S = 15
RECHECK_S = 300  # la session est revérifiée régulièrement : un compte désactivé ou déconnecté perd le flux


def _authorise(request: Request) -> str:
    row = _session_row(request)
    with tenant_session(str(row.tenant_id)) as db:  # transaction courte : aucune connexion n'est gardée pendant le flux
        u = db.get(m.User, row.user_id)
        if u is None or not u.is_active or not has_permission(u.role, "self.read"):
            raise HTTPException(403, "Permission requise : self.read")
    return str(row.tenant_id)


@router.get("/events")
async def events(request: Request):
    tenant = await run_in_threadpool(_authorise, request)

    async def stream():
        from redis.asyncio import Redis
        r = Redis.from_url(settings.redis_url)
        ps = r.pubsub()
        await ps.subscribe(channel(tenant))
        checked = datetime.now(timezone.utc)
        try:
            yield "retry: 2000\nevent: ready\ndata: {}\n\n"
            while not await request.is_disconnected():
                msg = await ps.get_message(ignore_subscribe_messages=True, timeout=HEARTBEAT_S)
                if msg and msg.get("type") == "message":
                    data = msg["data"].decode() if isinstance(msg["data"], bytes) else str(msg["data"])
                    yield f"event: change\ndata: {data}\n\n"
                else:
                    yield ": ping\n\n"
                if (datetime.now(timezone.utc) - checked).total_seconds() > RECHECK_S:
                    try:
                        await run_in_threadpool(_authorise, request)
                    except HTTPException:
                        yield "event: expired\ndata: {}\n\n"
                        return
                    checked = datetime.now(timezone.utc)
                await asyncio.sleep(0)
        finally:
            await ps.unsubscribe()
            await ps.aclose()
            await r.aclose()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
