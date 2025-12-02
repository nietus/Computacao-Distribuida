"""Modelos SQLAlchemy utilizados pelo MVP do Skin IA."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    """Obter um carimbo de data e hora no fuso UTC com consciência de timezone."""

    # Centralizar a criação de ``datetime`` evita esquecer ``timezone.utc`` em
    # outros pontos do código e garante consistência em auditorias.
    return datetime.now(timezone.utc)


class Client(Base):
    """Representa um cliente autenticado que consome a API."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    requests: Mapped[list["AnalysisRequest"]] = relationship("AnalysisRequest", back_populates="client")


class AnalysisRequest(Base):
    """Entidade que registra cada solicitação de análise enviada pelos clientes."""

    __tablename__ = "analysis_request"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    client: Mapped[Client] = relationship("Client", back_populates="requests")
    result: Mapped[AnalysisResult | None] = relationship("AnalysisResult", back_populates="request", uselist=False)


class AnalysisResult(Base):
    """Guarda o resultado final da análise, incluindo metadados adicionais."""

    __tablename__ = "analysis_result"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("analysis_request.id"), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    extra_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB().with_variant(Text, "sqlite"), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    request: Mapped[AnalysisRequest] = relationship("AnalysisRequest", back_populates="result")

    def to_dict(self) -> dict[str, str | float | dict[str, Any]]:
        """Converter o resultado em um dicionário pronto para respostas JSON."""

        # ``extra_json`` pode ser ``None`` quando ainda não coletamos detalhes,
        # por isso fazemos ``or {}`` para evitar valores nulos no payload.
        return {
            "label": self.label,
            "confidence": self.confidence,
            "extra": self.extra_json or {},
            "completed_at": self.completed_at.isoformat(),
        }


class IdempotencyKey(Base):
    """Controla o reuso seguro de requisições repetidas (Idempotency-Key)."""

    __tablename__ = "idempotency_keys"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: _utcnow() + timedelta(hours=72), nullable=False
    )
