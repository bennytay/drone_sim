from datetime import UTC, datetime
from drone_sim.context import FileRecord
from drone_sim.semantic_ranking import MetadataSemanticRanker
from drone_sim.context import DirectoryIndex
from pathlib import Path


def test_metadata_ranker_finds_synonym_without_reading_content() -> None:
    records = (FileRecord(path="exports/uav_specs.pdf", size_bytes=1, modified_at=datetime.now(UTC), modified_at_ns=1), FileRecord(path="notes.txt", size_bytes=1, modified_at=datetime.now(UTC), modified_at_ns=1))
    assert MetadataSemanticRanker().rank("aircraft limits", records)[0] == "exports/uav_specs.pdf"


def test_directory_search_accepts_metadata_only_ranker() -> None:
    index = DirectoryIndex.build(Path("examples/demo_deployment"))
    results = index.search("aircraft", semantic_ranker=MetadataSemanticRanker())
    assert results[0].path.startswith("aircraft/")
