"""Bounded deterministic tools exposed to the LLM edge, never arbitrary code."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from drone_sim.context import DeploymentState, DeterministicFileReader, DirectoryIndex, InspectionEvent


class ToolAuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    arguments: dict[str, Any]
    result_digest: str


class AgentToolRuntime:
    """Read-only tools limited to one deployment root and bounded result sizes."""
    def __init__(self, root: Path, state: DeploymentState, *, max_bytes: int = 64_000):
        self.index = DirectoryIndex.build(root)
        self.reader = DeterministicFileReader(root, max_file_bytes=max_bytes)
        self.state = state
        self.max_bytes = max_bytes
        self.ledger: list[ToolAuditEntry] = []

    def list_index(self) -> tuple[dict[str, Any], ...]:
        result = tuple(record.model_dump(mode="json") for record in self.index.records)
        self._record("list_index", {}, result)
        return result

    def search_files(self, query: str, limit: int = 5) -> tuple[str, ...]:
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        result = tuple(record.path for record in self.index.search(query, limit=limit))
        self._record("search_files", {"query": query, "limit": limit}, result)
        return result

    def parse_file(self, relative_path: str) -> dict[str, Any]:
        # DeterministicFileReader enforces non-symlink root confinement.
        parsed = self.reader.parse(relative_path)
        result = parsed.model_dump(mode="json")
        if len(str(result).encode()) > self.max_bytes:
            raise ValueError("tool result exceeds bounded output limit")
        self._record("parse_file", {"path": relative_path}, result)
        self.state.trace.append(InspectionEvent(timestamp=datetime.now(tz=UTC), field="agent_tool", query=relative_path, source_path=relative_path, reason="agent requested bounded deterministic parse", adapter=parsed.adapter, outcome="candidate_extracted"))
        return result

    def _record(self, name: str, arguments: dict[str, Any], result: object) -> None:
        import hashlib, json
        digest = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
        self.ledger.append(ToolAuditEntry(name=name, arguments=arguments, result_digest=digest))
