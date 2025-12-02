"""Carregamento do modelo TensorFlow e utilitários de inferência."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import numpy as np
import tensorflow as tf
from tensorflow.keras.models import Model

# Configure TensorFlow device usage
logger = logging.getLogger(__name__)

def _configure_tensorflow_device() -> None:
    """Configure TensorFlow device usage based on environment."""
    # Check if user explicitly wants CPU-only mode
    force_cpu = os.getenv("TENSORFLOW_FORCE_CPU", "1").lower() in ("1", "true", "yes")

    if force_cpu:
        try:
            # Hide GPU devices from TensorFlow to prevent CUDA errors
            tf.config.set_visible_devices([], 'GPU')
            logger.info("TensorFlow configured to use CPU only (TENSORFLOW_FORCE_CPU=1)")
        except Exception as e:
            logger.warning(f"Could not configure TensorFlow CPU-only mode: {e}")
    else:
        # Try to use GPU if available
        try:
            gpus = tf.config.list_physical_devices('GPU')
            if gpus:
                logger.info(f"TensorFlow will attempt to use GPU: {len(gpus)} device(s) found")
            else:
                logger.info("No GPU devices found, TensorFlow will use CPU")
        except Exception as e:
            logger.warning(f"Error detecting GPU devices: {e}. Falling back to CPU.")
            tf.config.set_visible_devices([], 'GPU')

# Apply device configuration at module import time
_configure_tensorflow_device()

DEFAULT_IMAGE_SIZE: tuple[int, int] = (192, 192)
DEFAULT_MODEL_PATH = Path(os.getenv("SKIN_IA_MODEL_PATH", "Artefatos/model/cnn_model.keras"))
CLASS_NAMES: list[str] = [
    "Acne and Rosacea Photos",
    "Actinic Keratosis Basal Cell Carcinoma and other Malignant Lesions",
    "Atopic Dermatitis Photos",
    "Cellulitis Impetigo and other Bacterial Infections",
    "Eczema Photos",
    "Exanthems and Drug Eruptions",
    "Herpes HPV and other STDs Photos",
    "Light Diseases and Disorders of Pigmentation",
    "Lupus and other Connective Tissue diseases",
    "Melanoma Skin Cancer Nevi and Moles",
    "Poison Ivy Photos and other Contact Dermatitis",
    "Psoriasis pictures Lichen Planus and related diseases",
    "Seborrheic Keratoses and other Benign Tumors",
    "Systemic Disease",
    "Tinea Ringworm Candidiasis and other Fungal Infections",
    "Urticaria Hives",
    "Vascular Tumors",
    "Vasculitis Photos",
    "Warts Molluscum and other Viral Infections"
]


@dataclass(frozen=True)
class Prediction:
    """Representa uma classificação individual retornada pelo modelo."""

    label: str
    confidence: float

    def to_dict(self) -> dict[str, float | str]:
        """Converter a previsão em um formato fácil de serializar em JSON."""

        return {"label": self.label, "confidence": self.confidence}


class SkinDiseaseClassifier:
    """Empacota um modelo TensorFlow treinado para classificar doenças de pele."""

    def __init__(
        self,
        model: Model,
        class_names: Sequence[str] = CLASS_NAMES,
        image_size: tuple[int, int] = DEFAULT_IMAGE_SIZE,
        model_path: Path | None = None,
    ) -> None:
        """Armazenar o modelo e metadados necessários para inferência."""

        # Guardamos o modelo carregado e normalizamos os parâmetros para tipos
        # simples (listas/tuplas) que serão utilizados durante a inferência.
        self._model = model
        self._class_names = list(class_names)
        self._image_size = image_size
        self._model_path = Path(model_path) if model_path else None

    @property
    def class_names(self) -> list[str]:
        """Listar os nomes das classes que o modelo conhece."""

        # Retornamos uma cópia para evitar que código externo altere o estado.
        return list(self._class_names)

    @property
    def image_size(self) -> tuple[int, int]:
        """Informar o tamanho esperado (altura, largura) das imagens de entrada."""
        return self._image_size

    @property
    def model_metadata(self) -> dict[str, str | int | list[int]]:
        """Montar metadados úteis sobre o modelo para auditoria e debugging."""

        # Expomos número de classes, tamanho da imagem e, se disponível, o
        # caminho do arquivo carregado para facilitar rastreabilidade.
        metadata: dict[str, str | int | list[int]] = {
            "num_classes": len(self._class_names),
            "image_size": list(self._image_size),
        }
        if self._model_path is not None:
            metadata["model_path"] = str(self._model_path)
        return metadata

    @classmethod
    def from_path(
        cls,
        model_path: Path | str,
        *,
        class_names: Sequence[str] = CLASS_NAMES,
        image_size: tuple[int, int] = DEFAULT_IMAGE_SIZE,
    ) -> "SkinDiseaseClassifier":
        """Carregar um modelo salvo em disco e criar o wrapper da aplicação."""

        # Utilizamos ``Path`` para garantir compatibilidade com strings ou
        # objetos ``Path`` recebidos do chamador.
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"Modelo não encontrado em {path}")
        model = tf.keras.models.load_model(path)
        return cls(model, class_names=class_names, image_size=image_size, model_path=path)

    def _preprocess(self, image_bytes: bytes) -> np.ndarray:
        """Transformar bytes de imagem em tensor pronto para inferência."""

        # Decodificamos a imagem para um tensor RGB com 3 canais.
        tensor = tf.io.decode_image(image_bytes, channels=3, expand_animations=False)  # pyright: ignore[reportAttributeAccessIssue]
        # Redimensionamos para o tamanho esperado pelo modelo.
        tensor = tf.image.resize(  # pyright: ignore[reportAttributeAccessIssue]
            tensor,
            self._image_size,
            method=tf.image.ResizeMethod.BILINEAR,  # pyright: ignore[reportAttributeAccessIssue]
        )
        # Normalizamos o tipo numérico para float32, padrão do TensorFlow.
        tensor = tf.cast(tensor, tf.float32)
        # Expandimos a dimensão do batch para que o modelo receba ``(1, H, W, C)``.
        tensor = tf.expand_dims(tensor, axis=0)
        return tensor.numpy()

    def predict(self, image_bytes: bytes, top_k: int = 3) -> tuple[Prediction, list[Prediction]]:
        """Executar a inferência e retornar a melhor previsão e o top-K completo."""

        # Pré-processamos os bytes e chamamos o modelo TensorFlow em uma thread
        # separada (o que ocorre fora deste método) para não bloquear o event loop.
        batch = self._preprocess(image_bytes)
        probabilities: np.ndarray = self._model.predict(batch, verbose=0)[0]
        # ``argsort`` em ordem decrescente seleciona as classes mais prováveis.
        top_indices = np.argsort(probabilities)[::-1][:top_k]
        predictions = [
            Prediction(label=self._class_names[index], confidence=float(probabilities[index]))
            for index in top_indices
        ]
        primary = predictions[0]
        return primary, predictions


@lru_cache(maxsize=1)
def get_default_classifier() -> SkinDiseaseClassifier:
    """Retornar um classificador singleton carregado do caminho padrão."""

    return SkinDiseaseClassifier.from_path(DEFAULT_MODEL_PATH)
