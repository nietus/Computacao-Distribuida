"""Utilitários para hash e verificação de chaves de API."""
from __future__ import annotations

from fastapi import HTTPException, status
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .models import Client

_password_hasher = PasswordHasher()


def verify_api_key(db_session, api_key: str) -> Client:
    """Validar a API key fornecida e retornar o cliente correspondente."""

    # Buscamos apenas clientes ativos para evitar autenticar registros revogados.
    active_clients = (
        db_session.query(Client).filter(Client.active.is_(True)).all()
    )
    for client in active_clients:
        try:
            if _password_hasher.verify(client.api_key_hash, api_key):
                return client
        except VerifyMismatchError:
            continue
    # Se nenhuma correspondência for encontrada, propagamos erro HTTP 401.
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key inválida ou inativa.")
