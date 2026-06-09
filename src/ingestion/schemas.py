from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class DocumentChunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)\n