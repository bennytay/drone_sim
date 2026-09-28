"""Provenance-qualified drone knowledge retrieval for hypothesis prompts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from drone_sim.context import DeterministicFileReader, DirectoryIndex
from drone_sim.failure_taxonomy import DEFAULT_FAILURE_TAXONOMY, FailureTaxonomy
from drone_sim.knowledge import (
    KnowledgeBundle,
    KnowledgeKind,
    KnowledgeSource,
    KnowledgeUse,
)

_TOKENS = re.compile(r"[a-z0-9]+")


def retrieve_knowledge(
    root: Path,
    *,
    taxonomy: FailureTaxonomy = DEFAULT_FAILURE_TAXONOMY,
    operator_sources: tuple[KnowledgeSource, ...] = (),
    external_sources: tuple[KnowledgeSource, ...] = (),
    model_world_prompts: tuple[str, ...] = (),
    retrieved_at: datetime | None = None,
) -> KnowledgeBundle:
    """Build a bundle without promoting prompt knowledge into deployment facts."""

    timestamp = retrieved_at or datetime.now(UTC)
    sources = [*_folder_sources(root, timestamp), *_platform_sources(taxonomy, timestamp)]
    sources.extend(operator_sources)
    sources.extend(external_sources)
    for index, summary in enumerate(model_world_prompts, start=1):
        sources.append(
            _source(
                identifier=f"model-world-{index}",
                kind=KnowledgeKind.MODEL_WORLD_KNOWLEDGE,
                title="Model world knowledge prompt",
                locator=f"model://hypothesis-prompt/{index}",
                retrieved_at=timestamp,
                summary=summary,
            )
        )
    if any(source.source_hash is None for source in sources):
        raise ValueError("retrieved knowledge sources require a content hash")
    return KnowledgeBundle(sources=tuple(sources))


def retrieve_for_hypothesis(
    bundle: KnowledgeBundle, query: str
) -> tuple[KnowledgeSource, ...]:
    tokens = set(_TOKENS.findall(query.lower()))
    scored = []
    for source in bundle.prompts():
        searchable = set(_TOKENS.findall(f"{source.title} {source.summary}".lower()))
        overlap = tokens & searchable
        if overlap:
            scored.append((len(overlap), source))
    return tuple(source for _, source in sorted(scored, key=lambda x: (-x[0], x[1].id)))


def _folder_sources(root: Path, timestamp: datetime) -> tuple[KnowledgeSource, ...]:
    index = DirectoryIndex.build(root)
    reader = DeterministicFileReader(root, max_file_bytes=64_000)
    sources = []
    for record in index.records:
        lowered = record.path.lower()
        if not any(
            token in lowered
            for token in ("manual", "manufacturer", "spec", "regulation", "rule", "limit", "brief")
        ):
            continue
        parsed = reader.parse(record.path)
        if isinstance(parsed.content, str):
            summary = " ".join(parsed.content.split())[:500]
        else:
            summary = json.dumps(parsed.content, sort_keys=True)[:500]
        if not summary:
            continue
        if any(token in lowered for token in ("regulation", "rule")):
            kind = KnowledgeKind.REGULATION
        elif any(token in lowered for token in ("site", "brief", "limit")):
            kind = KnowledgeKind.SITE_RULE
        else:
            kind = KnowledgeKind.MANUFACTURER
        sources.append(
            KnowledgeSource(
                id="folder-" + hashlib.sha256(record.path.encode()).hexdigest()[:16],
                kind=kind,
                title=Path(record.path).stem.replace("_", " "),
                locator=record.path,
                retrieved_at=timestamp,
                published_at=record.modified_at,
                source_hash=parsed.sha256,
                use=KnowledgeUse.HYPOTHESIS_PROMPT,
                summary=summary,
            )
        )
    return tuple(sources)


def _platform_sources(
    taxonomy: FailureTaxonomy, timestamp: datetime
) -> tuple[KnowledgeSource, ...]:
    return tuple(
        _source(
            identifier=f"platform-{leaf.id}",
            kind=KnowledgeKind.PLATFORM_KNOWLEDGE,
            title=leaf.name,
            locator=f"builtin://drone-failure-patterns/{leaf.id}",
            retrieved_at=timestamp,
            summary=(
                f"Drone incident pattern: {leaf.description} Causal variables: "
                f"{', '.join(leaf.causal_variables)}. Observable outcomes: "
                f"{', '.join(leaf.observable_outcomes)}."
            ),
        )
        for leaf in taxonomy.leaves()
    )


def _source(
    *,
    identifier: str,
    kind: KnowledgeKind,
    title: str,
    locator: str,
    retrieved_at: datetime,
    summary: str,
) -> KnowledgeSource:
    digest = hashlib.sha256(
        json.dumps(
            {"locator": locator, "summary": summary},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return KnowledgeSource(
        id=identifier,
        kind=kind,
        title=title,
        locator=locator,
        retrieved_at=retrieved_at,
        source_hash=digest,
        use=KnowledgeUse.HYPOTHESIS_PROMPT,
        summary=summary,
    )
