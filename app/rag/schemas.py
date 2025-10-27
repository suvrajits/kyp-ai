from pydantic import BaseModel
from typing import List, Optional

class IngestResponse(BaseModel):
    doc_id: str
    chunks: int
    tokens: int

class AskRequest(BaseModel):
    query: str
    top_k: int = 4

class AskAnswer(BaseModel):
    answer: str
    sources: List[str]  # list of "doc_id#chunk_idx" identifiers
    context_preview: List[str]  # first 120 chars of each chunk
