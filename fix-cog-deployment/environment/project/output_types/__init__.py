"""Output type definitions for the image processing pipeline."""
from pydantic import BaseModel
from typing import List, Optional


class ProcessingMetrics(BaseModel):
    """Metrics recorded during image processing."""
    processing_time: int
    gpu_memory_used: float
    model_version: str


class PipelineResult(BaseModel):
    """Result of the image processing pipeline."""
    output_image: str
    metrics: ProcessingMetrics
    caption: str
    tags: List[str]
