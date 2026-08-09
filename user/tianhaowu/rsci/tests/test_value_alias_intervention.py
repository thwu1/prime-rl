import pytest
from alias_shortcut import canonical_alias_opportunities
from strict_trajectory_grader import grade_trajectory
from value_alias_intervention import (
    ValueAliasInterventionError,
    build_value_alias_intervention,
    try_value_alias_opportunity,
)

GOLD = (
    "Define alpha as a; so a = 4. "
    "Define beta as b; so b = 4. "
    "Define gamma as c; so c = 1. "
    "Define total as d; so d = a + c = 4 + 1 = 5. Answer: 5."
)


def test_builds_validated_value_alias_intervention() -> None:
    intervention = build_value_alias_intervention(GOLD)

    assert intervention.transformed_solution == (
        "Define alpha as a; so a = 4. "
        "Define beta as b; so b = 4. "
        "Define gamma as c; so c = 1. "
        "Define total as d; so d = b + c = 4 + 1 = 5. Answer: 5."
    )
    assert (
        intervention.opportunity.child,
        intervention.opportunity.omitted_parent,
        intervention.opportunity.added_parent,
    ) == ("total", "alpha", "beta")
    assert grade_trajectory(GOLD, intervention.transformed_solution)["issue_codes"] == [
        "definition_dependency_mismatch",
        "dependency_mismatch",
    ]


def test_no_standalone_rhs_token_fails_closed() -> None:
    gold = "Define alpha as e; so e = 4. Define beta as f; so f = 4. Define total as g; so g = 4e0 = 4. Answer: 4."
    opportunities = canonical_alias_opportunities(gold)

    assert len(opportunities) == 1
    assert try_value_alias_opportunity(gold, opportunities[0]) is None
    with pytest.raises(ValueAliasInterventionError, match="No validated"):
        build_value_alias_intervention(gold)


def test_invalid_execution_fails_closed() -> None:
    gold = (
        "Define base as x; we don't know its value yet. "
        "Define alpha as a; so a = x + 1. "
        "Define beta as b; so b = 1. "
        "Define total as d; so d = a - x = 1. Answer: 1."
    )
    opportunity = canonical_alias_opportunities(gold)[0]

    assert grade_trajectory(gold, gold)["issue_codes"] == []
    assert try_value_alias_opportunity(gold, opportunity) is None
    with pytest.raises(ValueAliasInterventionError, match="No validated"):
        build_value_alias_intervention(gold)


def test_builder_skips_an_unrenderable_earlier_opportunity() -> None:
    gold = (
        "Define alpha as e; so e = 4. "
        "Define beta as f; so f = 4. "
        "Define gamma as g; so g = 1. "
        "Define aaa as h; so h = 4e0 = 4. "
        "Define zzz as i; so i = e + g = 4 + 1 = 5. Answer: 5."
    )
    opportunities = tuple(sorted(canonical_alias_opportunities(gold)))

    assert opportunities[0].child == "aaa"
    assert try_value_alias_opportunity(gold, opportunities[0]) is None
    intervention = build_value_alias_intervention(gold)
    assert intervention.opportunity == opportunities[1]
    assert intervention.opportunity.child == "zzz"
