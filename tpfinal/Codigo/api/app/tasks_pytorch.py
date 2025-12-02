"""Async analysis pipeline using PyTorch classifier."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .db import SessionLocal
from .ml.pytorch_model import get_pytorch_classifier
from .models import AnalysisRequest, AnalysisResult
from .queues import redis_publisher

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Generate UTC timezone-aware timestamp for records."""
    return datetime.now(timezone.utc)


def _publish(event_type: str, **payload: str | float | dict[str, object]) -> None:
    """Send standardized events to Redis queue with basic metadata."""
    event = {"type": event_type, "timestamp": _utcnow().isoformat(), **payload}
    redis_publisher.publish(event)


async def analyze_image_pytorch_async(request_id: str, image_bytes: bytes) -> None:
    """Execute inference using PyTorch model and persist result."""

    logger.info(f"[PyTorch] Starting analysis for request {request_id}")
    classifier = get_pytorch_classifier()

    with SessionLocal() as session:
        request = session.get(AnalysisRequest, request_id)
        if request is None:
            logger.warning(f"Request {request_id} not found for processing.")
            return

        request.status = "processing"
        request.updated_at = _utcnow()
        session.commit()

    _publish("analysis.started", request_id=request_id, framework="pytorch")

    try:
        # Execute model in worker thread to avoid blocking asyncio loop
        primary, top_predictions = await asyncio.to_thread(
            classifier.predict, image_bytes
        )
    except Exception as exc:
        logger.exception(f"Error executing PyTorch inference for {request_id}")
        with SessionLocal() as session:
            request = session.get(AnalysisRequest, request_id)
            if request is None:
                return
            request.status = "failed"
            request.error_message = str(exc)
            request.updated_at = _utcnow()
            session.commit()
        _publish("analysis.failed", request_id=request_id, error=str(exc), framework="pytorch")
        return

    with SessionLocal() as session:
        request = session.get(AnalysisRequest, request_id)
        if request is None:
            logger.warning(f"Request {request_id} not found to persist result.")
            return

        try:
            request.status = "completed"
            request.updated_at = _utcnow()
            result = AnalysisResult(
                request_id=request_id,
                label=primary.label,
                confidence=primary.confidence,
                extra_json={
                    "top_k": [prediction.to_dict() for prediction in top_predictions],
                    "model": classifier.model_metadata,
                    "framework": "pytorch",
                },
            )
            session.add(result)
        except Exception as exc:
            request.status = "failed"
            request.error_message = str(exc)
            request.updated_at = _utcnow()
            logger.exception(f"Error processing request {request_id}")
        finally:
            session.commit()

    _publish(
        "analysis.completed",
        request_id=request_id,
        label=primary.label,
        confidence=primary.confidence,
        framework="pytorch",
    )
    logger.info(f"[PyTorch] Completed analysis for request {request_id}: {primary.label} ({primary.confidence:.2%})")
