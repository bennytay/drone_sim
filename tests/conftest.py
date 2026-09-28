"""Assign every test module to one testing layer; see docs/TESTING.md."""

from pathlib import Path

import pytest


LAYERS = {
    "component": {
        "test_agent_tools.py",
        "test_document_extraction.py",
        "test_context_agent.py",
        "test_conflict_assistant.py",
        "test_schema_mapping.py",
        "test_semantic_ranking.py",
        "test_adapters.py",
        "test_capabilities.py",
        "test_coverage.py",
        "test_failure_taxonomy.py",
        "test_hypothesis.py",
        "test_interfaces.py",
        "test_investigation.py",
        "test_ir.py",
        "test_knowledge.py",
        "test_llm.py",
        "test_llm_ledger.py",
        "test_llm_safety.py",
        "test_llm_eval.py",
        "test_llm.py",
        "test_provenance.py",
        "test_registry.py",
        "test_stopping.py",
        "test_trust.py",
        "test_validation.py",
    },
    "integration": {
        "test_context.py",
        "test_graph.py",
        "test_routing.py",
        "test_synthetic_deployments.py",
    },
    "golden": {"test_golden_path.py"},
}

_LAYER_BY_FILE = {name: layer for layer, names in LAYERS.items() for name in names}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    unclassified = set()
    for item in items:
        name = Path(str(item.fspath)).name
        layer = _LAYER_BY_FILE.get(name)
        if layer is None:
            unclassified.add(name)
            continue
        item.add_marker(getattr(pytest.mark, layer))
    if unclassified:
        raise pytest.UsageError(
            "Assign these test modules to a layer in tests/conftest.py: "
            + ", ".join(sorted(unclassified))
        )
