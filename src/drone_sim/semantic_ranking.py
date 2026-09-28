"""Metadata-only semantic-ish ranker for deployment folder discovery."""
from __future__ import annotations
import re
from collections.abc import Sequence
from drone_sim.context import FileRecord
_TOKEN = re.compile(r"[a-z0-9]+")
_SYNONYMS = {"aircraft": {"uav", "drone", "vehicle", "airframe"}, "route": {"flight", "waypoint", "mission", "plan"}, "wind": {"weather", "forecast", "met"}}
class MetadataSemanticRanker:
    """Ranks filenames/media metadata only; it cannot inspect customer bytes."""
    def rank(self, query: str, records: Sequence[FileRecord]) -> Sequence[str]:
        expanded = set(_TOKEN.findall(query.lower()))
        expanded |= {word for token in tuple(expanded) for word in _SYNONYMS.get(token, set())}
        return tuple(record.path for record in sorted(records, key=lambda record: (-len(set(_TOKEN.findall(record.path.lower())) & expanded), record.path)))
