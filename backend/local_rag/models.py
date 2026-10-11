from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class HistoryTurn(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=4000)
    scope_node_id: str | None = None
    group_ids: list[str] = Field(default_factory=list, max_length=100)
    mode: Literal["hybrid", "keyword", "semantic"] = "hybrid"
    history: list[HistoryTurn] = Field(default_factory=list, max_length=8)


class SourceReference(StrictModel):
    id: str
    node_id: str
    title: str
    path: list[str]
    locator: str = ""
    source_url: str | None = None


class Chunk(StrictModel):
    id: str
    node_id: str
    title: str
    text: str
    path: list[str]
    locator: str = ""
    source_url: str | None = None
    coverage_note: str | None = None
    source_refs: list[SourceReference] = Field(default_factory=list)
    # Original complete subunits are backend-only fallbacks for oversized joins.
    _parts: list['Chunk'] = PrivateAttr(default_factory=list)


class Node(StrictModel):
    id: str
    parent_id: str | None
    title: str
    kind: str
    description: str
    path: list[str]
    child_count: int
    chunk_count: int
    status: str
    source_url: str | None = None
    coverage_note: str | None = None


class ModelAnswer(StrictModel):
    """Small model contract; source objects are assembled by the backend."""
    answer: str = Field(min_length=1, max_length=8000)
    citation_ids: list[str] = Field(max_length=12)
    insufficient_evidence: bool


class TraceStep(StrictModel):
    name: str
    status: Literal['completed', 'skipped', 'failed']
    detail: str
    duration_ms: float = Field(default=0.0, ge=0)
    result_count: int | None = None
    result_ids: list[str] = Field(default_factory=list)


class SearchTrace(StrictModel):
    query: str
    mode: str
    scope_node_id: str | None = None
    group_ids: list[str] = Field(default_factory=list)
    expansions: list[str] = Field(default_factory=list)
    steps: list[TraceStep] = Field(default_factory=list)


class ChatResponse(StrictModel):
    answer: str
    citations: list[Chunk]
    insufficient_evidence: bool
    coverage_note: str | None = None
    trace: SearchTrace | None = None


class SearchResponse(StrictModel):
    results: list[Chunk]
    coverage_note: str | None = None
    trace: SearchTrace | None = None


class Theme(StrictModel):
    primary: str
    secondary: str


class PublicConfig(StrictModel):
    theme: Theme
    total_chunks: int
    total_nodes: int


class NodePage(StrictModel):
    nodes: list[Node]
    next_cursor: str | None = None


class ChunkPage(StrictModel):
    chunks: list[Chunk]


class MapPoint(StrictModel):
    id: str
    chunk_id: str
    node_id: str
    title: str
    path: list[str]
    group_id: str | None
    x: float
    y: float


class MapGroup(StrictModel):
    id: str
    title: str


class MapPage(StrictModel):
    points: list[MapPoint]
    groups: list[MapGroup]
    total_points: int
    next_cursor: str | None = None
    coverage_note: str | None = None
    trace: SearchTrace | None = None


class Issue(StrictModel):
    id: str
    title: str
    message: str
    locator: str
    status: str
    node_id: str | None = None
    source_title: str | None = None
    path: list[str] = Field(default_factory=list)
    question: str | None = None
    affected_count: int = Field(default=1, ge=0)
    affected_unit: str = "records"
    severity: str = "warning"


class IssuePage(StrictModel):
    issues: list[Issue]
