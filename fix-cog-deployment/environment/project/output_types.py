from cog import BaseModel, Path
from typing import Union, List, Optional


class ProcessingMetrics(BaseModel):
    processing_time: float
    gpu_memory_used: float
    model_version: str


class PipelineResult(BaseModel):
    output_image: Path
    metrics: ProcessingMetrics
    caption: Union[str, int]
    tags: List[str]
    watermark: Optional[str] = None
