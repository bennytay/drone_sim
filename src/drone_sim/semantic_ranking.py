"""Cached metadata-only semantic ranking for deployment folder discovery."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import ConfigDict, Field

from drone_sim.context import FileRecord
from drone_sim.ir import StrictModel
from drone_sim.llm import (
    LLMMessage,
    LLMTask,
    MessageRole,
    Prompt,
    StructuredOutputRunner,
)

_TOKEN = re.compile(r"[a-z0-9]+")
_SYNONYMS = {
    "aircraft": {"uav", "drone", "vehicle", "airframe"},
    "route": {"flight", "waypoint", "mission", "plan", "kml", "geojson"},
    "wind": {"weather", "forecast", "met"},
    "battery": {"energy", "pack", "power"},
    "telemetry": {"log", "flight", "ulg", "mcap", "csv"},
}


def _index_signature(records: Sequence[FileRecord]) -> str:
    value = [
        (item.path, item.size_bytes, item.media_type, item.modified_at_ns)
        for item in records
    ]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class RankingMetrics:
    recall_at_limit: float
    mean_files_returned: float


class RankedPaths(StrictModel):
    """Contract returned by a metadata-only LLM ranking call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    paths: tuple[str, ...] = Field(min_length=1)


class LLMSemanticRanker:
    """Rank file metadata with a contract-validated LLM and durable cache."""

    def __init__(
        self,
        runner: StructuredOutputRunner,
        *,
        model: str,
        cache_path: Path | None = None,
    ) -> None:
        self.runner = runner
        self.model = model
        self.cache_path = cache_path
        self._cache: dict[str, tuple[str, ...]] = {}
        if cache_path and cache_path.exists():
            loaded = json.loads(cache_path.read_text())
            self._cache = {key: tuple(value) for key, value in loaded.items()}

    def rank(self, query: str, records: Sequence[FileRecord]) -> Sequence[str]:
        cache_key = f"{_index_signature(records)}:{query.casefold()}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        metadata = [
            {
                "path": record.path,
                "size_bytes": record.size_bytes,
                "media_type": record.media_type,
                "modified_at": record.modified_at.isoformat(),
            }
            for record in records
        ]
        prompt = Prompt(
            id="semantic-file-ranking",
            version="1",
            messages=(
                LLMMessage(
                    role=MessageRole.SYSTEM,
                    content=(
                        "Rank drone deployment files for the requested canonical field. "
                        "Use only the supplied metadata and return JSON matching the contract."
                    ),
                ),
                LLMMessage(
                    role=MessageRole.USER,
                    content=json.dumps({"query": query, "files": metadata}, sort_keys=True),
                ),
            ),
        )
        ranked, _ = self.runner.run(
            task=LLMTask.EXTRACTION,
            model=self.model,
            prompt=prompt,
            contract=RankedPaths,
        )
        allowed = {record.path for record in records}
        if len(set(ranked.paths)) != len(ranked.paths) or not set(ranked.paths) <= allowed:
            raise ValueError("semantic ranker returned duplicate or unknown paths")
        self._cache[cache_key] = ranked.paths
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self._cache, indent=2, sort_keys=True) + "\n"
            )
        return ranked.paths


class MetadataSemanticRanker:
    """Rank paths and media types, caching by the complete index signature."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[str, ...]] = {}
        self.computations = 0

    def rank(self, query: str, records: Sequence[FileRecord]) -> Sequence[str]:
        key = (_index_signature(records), query.casefold())
        if key in self._cache:
            return self._cache[key]
        expanded = set(_TOKEN.findall(query.lower()))
        expanded |= {
            word
            for token in tuple(expanded)
            for word in _SYNONYMS.get(token, set())
        }
        scored: list[tuple[int, str]] = []
        for record in records:
            metadata = f"{record.path} {record.media_type or ''}".lower()
            overlap = set(_TOKEN.findall(metadata)) & expanded
            if overlap:
                scored.append((len(overlap), record.path))
        ranked = tuple(
            path for _, path in sorted(scored, key=lambda item: (-item[0], item[1]))
        )
        self._cache[key] = ranked
        self.computations += 1
        return ranked


def evaluate_ranking(
    ranker: MetadataSemanticRanker,
    records: Sequence[FileRecord],
    cases: tuple[tuple[str, str], ...],
    *,
    limit: int = 5,
) -> RankingMetrics:
    hits = returned = 0
    for query, expected_path in cases:
        paths = tuple(ranker.rank(query, records))[:limit]
        hits += expected_path in paths
        returned += len(paths)
    return RankingMetrics(
        hits / len(cases) if cases else 1.0,
        returned / len(cases) if cases else 0.0,
    )
