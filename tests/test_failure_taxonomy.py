import pytest
from pydantic import ValidationError

from drone_sim.failure_taxonomy import (
    DEFAULT_FAILURE_TAXONOMY,
    FailureDomain,
    FailureTaxonomy,
    TaxonomyNode,
)


def test_default_taxonomy_covers_every_required_drone_domain() -> None:
    taxonomy = DEFAULT_FAILURE_TAXONOMY

    assert {category.domain for category in taxonomy.categories} == set(FailureDomain)
    assert len(taxonomy.leaves()) >= 25
    assert len({leaf.id for leaf in taxonomy.leaves()}) == len(taxonomy.leaves())


def test_leaves_carry_testable_causal_contracts() -> None:
    for leaf in DEFAULT_FAILURE_TAXONOMY.leaves():
        assert leaf.causal_variables
        assert leaf.observable_outcomes
        assert all(path.startswith("/") for path in leaf.context_paths)


def test_representative_deployments_have_specific_surfaces() -> None:
    leaves = DEFAULT_FAILURE_TAXONOMY.leaves()

    for deployment_tag, minimum in {
        "urban": 8,
        "inspection": 6,
        "bvlos": 5,
        "delivery": 5,
        "mapping": 4,
    }.items():
        assert (
            len([leaf for leaf in leaves if deployment_tag in leaf.deployment_tags])
            >= minimum
        )


def test_upstream_development_failures_are_explicitly_excluded() -> None:
    excluded = " ".join(DEFAULT_FAILURE_TAXONOMY.excluded_upstream_failures)

    assert "flight-control" in excluded
    assert "manufacturing" in excluded
    assert "software correctness" in excluded


def test_leaf_without_test_semantics_is_rejected() -> None:
    with pytest.raises(ValidationError, match="leaf nodes require"):
        TaxonomyNode(
            id="environment_weather.invalid", name="Invalid", description="No contract"
        )


def test_taxonomy_rejects_missing_domains() -> None:
    data = DEFAULT_FAILURE_TAXONOMY.model_dump()
    data["categories"] = data["categories"][:-1]

    with pytest.raises(ValidationError, match="each failure domain exactly once"):
        FailureTaxonomy.model_validate(data)
