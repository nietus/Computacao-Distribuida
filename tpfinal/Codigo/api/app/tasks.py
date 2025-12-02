"""Pipeline assíncrona de análise que utiliza o classificador TensorFlow."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from . import hardware
from .db import SessionLocal
from .ml import get_default_classifier
from .models import AnalysisRequest, AnalysisResult
from .queues import redis_publisher

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Gerar timestamp em UTC consciente de timezone para registros."""

    # Centralizamos esta lógica para manter consistência na auditoria dos eventos.
    return datetime.now(timezone.utc)


def _log_execution_backend() -> None:
    """Registrar em log qual acelerador está disponível para a pipeline."""

    info = hardware.detect_torch_device()
    logger.info(
        "Pipeline configurada para usar %s (%s) na plataforma %s.",
        info.device,
        info.detail,
        info.platform,
    )


def _publish(event_type: str, **payload: str | float | dict[str, object]) -> None:
    """Enviar eventos padronizados para a fila do Redis com metadados básicos."""

    # Compondo um envelope único garantimos que todos os eventos tenham
    # ``timestamp`` e ``type``, facilitando o consumo por serviços externos.
    event = {"type": event_type, "timestamp": _utcnow().isoformat(), **payload}
    redis_publisher.publish(event)


async def analyze_image_async(request_id: str, image_bytes: bytes) -> None:
    """Executar a inferência da imagem recebida e persistir o resultado."""

    # Registrar o backend ajuda na observabilidade quando alternamos entre CPU e GPU.
    _log_execution_backend()
    classifier = get_default_classifier()

    with SessionLocal() as session:
        # Recuperamos a requisição para validar se ela existe antes de processar.
        request = session.get(AnalysisRequest, request_id)
        if request is None:
            logger.warning("Request %s não encontrada para processamento.", request_id)
            return

        request.status = "processing"
        request.updated_at = _utcnow()
        session.commit()

    _publish("analysis.started", request_id=request_id)

    try:
        # A execução do modelo ocorre em thread de trabalho para não bloquear o asyncio loop.
        primary, top_predictions = await asyncio.to_thread(
            classifier.predict, image_bytes
        )
    except Exception as exc:  # pragma: no cover - dependências externas
        logger.exception("Erro ao executar inferência para %s", request_id)
        with SessionLocal() as session:
            # Em caso de falha, registramos o erro na requisição para inspeção posterior.
            request = session.get(AnalysisRequest, request_id)
            if request is None:
                return
            request.status = "failed"
            request.error_message = str(exc)
            request.updated_at = _utcnow()
            session.commit()
        _publish("analysis.failed", request_id=request_id, error=str(exc))
        return

    with SessionLocal() as session:
        # Abrimos nova sessão para garantir que estamos lendo o estado mais recente do banco.
        request = session.get(AnalysisRequest, request_id)
        if request is None:
            logger.warning("Request %s não encontrada para persistir resultado.", request_id)
            return

        try:
            request.status = "completed"
            request.updated_at = _utcnow()
            result = AnalysisResult(
                request_id=request_id,
                label=primary.label,
                confidence=primary.confidence,
                extra_json={
                    # Serializamos as principais previsões e metadados do modelo
                    # para manter transparência com o cliente final.
                    "top_k": [prediction.to_dict() for prediction in top_predictions],
                    "model": classifier.model_metadata,
                },
            )
            session.add(result)
        except Exception as exc:  # pragma: no cover - proteção defensiva
            request.status = "failed"
            request.error_message = str(exc)
            request.updated_at = _utcnow()
            logger.exception("Erro ao processar request %s", request_id)
        finally:
            session.commit()

    _publish(
        "analysis.completed",
        request_id=request_id,
        label=primary.label,
        confidence=primary.confidence,
    )
