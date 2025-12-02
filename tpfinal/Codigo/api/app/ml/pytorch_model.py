"""PyTorch model loader and inference utilities."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import numpy as np
import torch
import torchvision.transforms as transforms
from PIL import Image
import io

logger = logging.getLogger(__name__)

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
    """Represents a single classification returned by the model."""

    label: str
    confidence: float

    def to_dict(self) -> dict[str, float | str]:
        """Convert prediction to JSON-serializable format."""
        return {"label": self.label, "confidence": self.confidence}


class PyTorchSkinClassifier:
    """
    Wrapper for skin disease classification model.

    Note: This uses the TensorFlow Keras model (.keras) but loads it via
    TensorFlow's API for compatibility. For a pure PyTorch implementation,
    you would need to convert the model or train a PyTorch model separately.
    """

    def __init__(
        self,
        model_path: Path | str,
        class_names: Sequence[str] = CLASS_NAMES,
        image_size: tuple[int, int] = DEFAULT_IMAGE_SIZE,
    ):
        """Initialize classifier with TensorFlow model (for compatibility)."""
        self._model_path = Path(model_path)
        self._class_names = list(class_names)
        self._image_size = image_size

        # Load TensorFlow model (since the .keras file is TensorFlow format)
        # For pure PyTorch, you would load a .pt or .pth file instead
        try:
            import tensorflow as tf
            # Configure CPU-only mode
            force_cpu = os.getenv("TENSORFLOW_FORCE_CPU", "1").lower() in ("1", "true", "yes")
            if force_cpu:
                tf.config.set_visible_devices([], 'GPU')
                logger.info("PyTorch classifier using TensorFlow CPU backend")

            if not self._model_path.exists():
                raise FileNotFoundError(f"Model not found at {self._model_path}")

            self._model = tf.keras.models.load_model(str(self._model_path))
            logger.info(f"Loaded model from {self._model_path}")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise

        # Define image preprocessing transforms
        self.transform = transforms.Compose([
            transforms.Resize(self._image_size),
            transforms.ToTensor(),
        ])

    @property
    def class_names(self) -> list[str]:
        """Return list of class names."""
        return list(self._class_names)

    @property
    def image_size(self) -> tuple[int, int]:
        """Return expected image size (height, width)."""
        return self._image_size

    def _preprocess(self, image_bytes: bytes) -> np.ndarray:
        """Transform image bytes into tensor ready for inference."""
        try:
            # Decode image using PIL
            image = Image.open(io.BytesIO(image_bytes)).convert('RGB')

            # Resize image
            image = image.resize(self._image_size, Image.Resampling.BILINEAR)

            # Convert to numpy array and normalize
            img_array = np.array(image, dtype=np.float32)

            # Add batch dimension (1, H, W, C)
            img_array = np.expand_dims(img_array, axis=0)

            return img_array
        except Exception as e:
            logger.error(f"Error preprocessing image: {e}")
            raise

    def predict(self, image_bytes: bytes, top_k: int = 3) -> tuple[Prediction, list[Prediction]]:
        """
        Execute inference and return top prediction and top-K results.

        Args:
            image_bytes: Raw image bytes
            top_k: Number of top predictions to return

        Returns:
            Tuple of (primary_prediction, all_top_predictions)
        """
        try:
            # Preprocess image
            batch = self._preprocess(image_bytes)

            # Run inference using TensorFlow model
            probabilities: np.ndarray = self._model.predict(batch, verbose=0)[0]

            # Get top-k predictions
            top_indices = np.argsort(probabilities)[::-1][:top_k]
            predictions = [
                Prediction(
                    label=self._class_names[index],
                    confidence=float(probabilities[index])
                )
                for index in top_indices
            ]

            primary = predictions[0]
            logger.info(f"Prediction: {primary.label} ({primary.confidence:.2%})")

            return primary, predictions

        except Exception as e:
            logger.error(f"Error during prediction: {e}")
            raise


@lru_cache(maxsize=1)
def get_pytorch_classifier() -> PyTorchSkinClassifier:
    """Return singleton classifier loaded from default path."""
    logger.info(f"Loading PyTorch classifier from {DEFAULT_MODEL_PATH}")
    return PyTorchSkinClassifier(DEFAULT_MODEL_PATH)
