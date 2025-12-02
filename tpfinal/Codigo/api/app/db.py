"""Configuração do banco de dados para a aplicação FastAPI do Skin IA."""
from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./skinia.db")


def _create_engine(url: str):
    """Criar uma engine SQLAlchemy configurada para o backend disponível."""

    # Para SQLite ativamos ``check_same_thread`` para permitir uso em threads
    # diferentes durante os testes ou execução local. Outros bancos não
    # necessitam desse parâmetro.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)

engine = _create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()


def init_db() -> None:
    """Criar as tabelas do banco durante a inicialização da API."""
    from . import models  # noqa: F401  # Ensure models are imported

    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope():
    """Fornecer um escopo transacional simplificado para operações de banco."""

    # Abrimos uma nova sessão e garantimos que ela será fechada, mesmo se
    # ocorrerem exceções dentro do bloco ``with`` de quem chama esta função.
    session = SessionLocal()
    try:
        yield session
        # Após o bloco do chamador, persistimos as alterações realizadas.
        session.commit()
    except Exception:
        # Qualquer exceção leva a um rollback para manter a consistência.
        session.rollback()
        raise
    finally:
        # Por fim, liberamos a conexão com o banco.
        session.close()
