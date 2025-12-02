"""Model loading utilities for the Skin IA API."""
from .model import (
    CLASS_NAMES,
    SkinDiseaseClassifier,
    get_default_classifier,
    Prediction,
)

__all__ = [
    "CLASS_NAMES",
    "SkinDiseaseClassifier",
    "get_default_classifier",
    "Prediction",
]
