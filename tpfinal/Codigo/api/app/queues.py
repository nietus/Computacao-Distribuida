"""Utilitários de Redis responsáveis por publicar eventos de análise."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class RedisEventPublisher:
    """Publicador simples responsável por enviar eventos JSON para o Redis."""

    def __init__(self, url: str | None, queue_name: str = "analysis_queue") -> None:
        """Configurar o publicador com a URL do Redis e o nome da fila."""

        # Guardamos os parâmetros para uso posterior e adiamos a conexão real
        # até o primeiro publish, evitando custos durante a inicialização.
        self._url = url
        self._queue_name = queue_name
        self._client: Redis | None = None

    def _get_client(self) -> Redis | None:
        """Criar (lazy) e retornar o cliente Redis configurado para a fila."""

        # Quando a URL não está definida, tratamos como cenário sem Redis e
        # retornamos ``None`` para evitar exceções.
        if not self._url:
            return None
        if self._client is None:
            # ``decode_responses`` garante strings ao invés de bytes.
            self._client = Redis.from_url(self._url, decode_responses=True)
        return self._client

    def publish(self, event: dict[str, Any]) -> None:
        """Enviar um evento serializado como JSON para a lista configurada."""

        # Tentamos obter o cliente; se não houver Redis configurado apenas
        # finalizamos silenciosamente para manter o comportamento "best effort".
        client = self._get_client()
        if client is None:
            return
        try:
            client.rpush(self._queue_name, json.dumps(event))
        except RedisError as exc:
            logger.warning("Falha ao publicar evento no Redis: %s", exc)


redis_publisher = RedisEventPublisher(
    os.getenv("REDIS_URL"),
    os.getenv("SKIN_IA_REDIS_QUEUE", "analysis_queue"),
)
