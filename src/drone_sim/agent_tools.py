"""Bounded deterministic tools exposed to the LLM edge, never arbitrary code."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from drone_sim.context import (
    DeploymentState,
    DeterministicFileReader,
    DirectoryIndex,
    InspectionEvent,
    StateStore,
)
from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY
from drone_sim.llm import ToolDefinition


class ToolAuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    arguments: dict[str, Any]
    result_digest: str
    timestamp: datetime


TOOL_DEFINITIONS = (
    ToolDefinition(name="list_index", description="List deployment file metadata.", input_schema={"type": "object", "properties": {}, "additionalProperties": False}),
    ToolDefinition(name="search_files", description="Rank deployment files by metadata.", input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["query"], "additionalProperties": False}),
    ToolDefinition(name="parse_file", description="Parse one confined deployment file with a bounded adapter.", input_schema={"type": "object", "properties": {"relative_path": {"type": "string"}}, "required": ["relative_path"], "additionalProperties": False}),
    ToolDefinition(name="read_text_span", description="Read a bounded line span from one deployment document.", input_schema={"type": "object", "properties": {"relative_path": {"type": "string"}, "line_start": {"type": "integer", "minimum": 1}, "line_end": {"type": "integer", "minimum": 1}}, "required": ["relative_path", "line_start", "line_end"], "additionalProperties": False}),
    ToolDefinition(name="taxonomy_lookup", description="Look up one drone failure taxonomy leaf.", input_schema={"type": "object", "properties": {"mechanism_id": {"type": "string"}}, "required": ["mechanism_id"], "additionalProperties": False}),
)


class AgentToolRuntime:
    """Read-only tools limited to one deployment root and bounded result sizes."""
    def __init__(self, root: Path, state: DeploymentState, *, max_bytes: int = 64_000, ledger_path: Path | None = None, state_path: Path | None = None):
        self.index = DirectoryIndex.build(root)
        self.reader = DeterministicFileReader(root, max_file_bytes=max_bytes)
        self.state = state
        self.max_bytes = max_bytes
        self.ledger_path = ledger_path
        self.state_path = state_path
        self.ledger: list[ToolAuditEntry] = (
            [ToolAuditEntry.model_validate(item) for item in json.loads(ledger_path.read_text())]
            if ledger_path and ledger_path.exists() else []
        )

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
        return result

    def read_text_span(self, relative_path: str, line_start: int, line_end: int) -> str:
        if line_start < 1 or line_end < line_start or line_end - line_start >= 100:
            raise ValueError("line span must contain between 1 and 100 lines")
        parsed = self.reader.parse(relative_path)
        if not isinstance(parsed.content, str):
            raise ValueError("read_text_span requires a text document")
        lines = parsed.content.splitlines()
        if line_end > len(lines):
            raise ValueError("line span is outside the document")
        result = "\n".join(lines[line_start - 1:line_end])
        if len(result.encode()) > self.max_bytes:
            raise ValueError("tool result exceeds bounded output limit")
        self._record("read_text_span", {"path": relative_path, "line_start": line_start, "line_end": line_end}, result)
        return result

    def taxonomy_lookup(self, mechanism_id: str) -> dict[str, Any]:
        leaf = next((item for item in DEFAULT_FAILURE_TAXONOMY.leaves() if item.id == mechanism_id), None)
        if leaf is None:
            raise KeyError(mechanism_id)
        result = leaf.model_dump(mode="json")
        self._record("taxonomy_lookup", {"mechanism_id": mechanism_id}, result)
        return result

    def _record(self, name: str, arguments: dict[str, Any], result: object) -> None:
        digest = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
        timestamp = datetime.now(tz=UTC)
        self.ledger.append(ToolAuditEntry(name=name, arguments=arguments, result_digest=digest, timestamp=timestamp))
        self.state.trace.append(InspectionEvent(timestamp=timestamp, field="agent_tool", query=name, source_path=arguments.get("path"), reason=f"agent called bounded deterministic tool {name}", outcome="candidate_extracted"))
        if self.ledger_path:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            self.ledger_path.write_text(json.dumps([entry.model_dump(mode="json") for entry in self.ledger], indent=2) + "\n")
        if self.state_path:
            StateStore(self.state_path, self.index.root).save(self.state)
