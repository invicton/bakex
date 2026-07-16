# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""AI Builder API — SSE-streaming agentic build endpoint."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from bakex.core.agent import AgentResult, run_build_agent
from bakex.core.llm import provider_status

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentBuildRequest(BaseModel):
    blueprint_yaml: str
    provider: str


@router.post("/build")
async def agent_build(req: AgentBuildRequest) -> StreamingResponse:
    """Trigger an agentic build. Returns an SSE stream of narration + result events.

    Event types:
      data: {"type": "narration", "text": "..."}   — streaming narration token
      data: {"type": "result",    "data": {...}}    — final AgentResult
      data: {"type": "error",     "message": "..."}  — fatal error
    """
    status = provider_status()
    if not status["available"]:
        raise HTTPException(status_code=400, detail=status["message"])

    blueprint_yaml = req.blueprint_yaml.strip()
    if not blueprint_yaml:
        raise HTTPException(status_code=400, detail="blueprint_yaml is required")

    async def event_stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def on_token(text: str) -> None:
            payload = json.dumps({"type": "narration", "text": text})
            await queue.put(f"data: {payload}\n\n")

        async def run_agent() -> None:
            try:
                result: AgentResult = await run_build_agent(
                    blueprint_yaml=blueprint_yaml,
                    provider=req.provider,
                    on_token=on_token,
                )
                payload = json.dumps(
                    {
                        "type": "result",
                        "data": {
                            "success": result.success,
                            "artifact_id": result.artifact_id,
                            "grade": result.grade,
                            "score_pct": result.score_pct,
                            "summary": result.summary,
                            "error": result.error,
                            "retries_used": result.retries_used,
                            "job_id": result.job_id,
                            "final_blueprint_yaml": result.final_blueprint_yaml,
                        },
                    }
                )
                await queue.put(f"data: {payload}\n\n")
            except Exception as exc:
                payload = json.dumps({"type": "error", "message": str(exc)})
                await queue.put(f"data: {payload}\n\n")
            finally:
                await queue.put(None)  # Sentinel — stream done

        # Run agent in background task; yield SSE events as they arrive
        task = asyncio.create_task(run_agent())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


@router.get("/status")
async def agent_status() -> dict:
    """Check whether the AI Builder is available and which backend is configured."""
    return provider_status()
