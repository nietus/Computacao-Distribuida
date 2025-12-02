"""Funções auxiliares para detectar aceleradores disponíveis em tempo de execução."""
from __future__ import annotations

import importlib.util
import logging
import platform
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TorchDeviceInfo:
    """Resumo do melhor dispositivo Torch disponível no ambiente."""

    device: str
    platform: str
    detail: str


def _load_torch():  # pragma: no cover - exercised via higher-level helpers
    """Importar ``torch`` sob demanda quando a dependência estiver instalada."""

    # Utilizar ``importlib`` evita ``ImportError`` quando rodamos sem PyTorch,
    # permitindo que a API continue funcional em ambientes somente CPU.
    if importlib.util.find_spec("torch") is None:
        return None
    import torch  # type: ignore

    return torch


@lru_cache()
def detect_torch_device() -> TorchDeviceInfo:
    """Descobrir o acelerador mais poderoso disponível no host de forma didática."""

    # Verificamos CUDA (Windows/Linux) e o backend MPS (macOS). Caso nenhum
    # acelerador esteja acessível, fazemos fallback para CPU para manter o serviço.

    torch = _load_torch()
    current_platform = platform.system()

    if torch is None:
        logger.info("PyTorch não encontrado; executando exclusivamente na CPU.")
        return TorchDeviceInfo(
            device="cpu",
            platform=current_platform,
            detail="PyTorch não instalado.",
        )

    if torch.cuda.is_available():
        try:  # defensive guard—APIs might fail if drivers are misconfigured
            index = torch.cuda.current_device()
            name = torch.cuda.get_device_name(index)
            detail = f"CUDA disponível ({name})."
        except Exception:  # pragma: no cover - hardware dependent
            detail = "CUDA disponível."
        logger.info("Selecionando CUDA para execução em \"%s\".", current_platform)
        return TorchDeviceInfo(device="cuda", platform=current_platform, detail=detail)

    mps_backend = getattr(torch.backends, "mps", None)
    is_built = getattr(mps_backend, "is_built", lambda: False)
    is_available = getattr(mps_backend, "is_available", lambda: False)
    if is_built() and is_available():
        logger.info("Selecionando backend MPS para execução em macOS.")
        return TorchDeviceInfo(
            device="mps",
            platform=current_platform,
            detail="Metal Performance Shaders (MPS) disponível.",
        )

    logger.info("Nenhum acelerador encontrado; utilizando CPU.")
    return TorchDeviceInfo(
        device="cpu",
        platform=current_platform,
        detail="Sem acelerador suportado; usando CPU.",
    )


def torch_device_or_none():
    """Retornar ``torch.device`` quando PyTorch estiver instalado no ambiente."""

    torch = _load_torch()
    if torch is None:
        return None
    info = detect_torch_device()
    return torch.device(info.device)
