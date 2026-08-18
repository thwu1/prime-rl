from alias_shortcut import canonical_alias_opportunities, find_alias_substitutions

GOLD = (
    "Define alpha as a; so a = 4. "
    "Define beta as b; so b = 4. "
    "Define gamma as c; so c = 1. "
    "Define total as d; so d = a + c = 4 + 1 = 5. Answer: 5."
)


def test_finds_value_alias_parent_substitution() -> None:
    prediction = (
        "Define alpha as a; so a = 4. "
        "Define beta as b; so b = 4. "
        "Define gamma as c; so c = 1. "
        "Define total as d; so d = b + c = 4 + 1 = 5. Answer: 5."
    )

    substitutions = find_alias_substitutions(GOLD, prediction)

    assert [substitution.to_dict() for substitution in substitutions] == [
        {
            "child": "total",
            "omitted_parent": "alpha",
            "added_parent": "beta",
            "shared_value": 4.0,
        }
    ]


def test_rejects_unequal_parent_values() -> None:
    prediction = (
        "Define alpha as a; so a = 4. "
        "Define beta as b; so b = 3. "
        "Define gamma as c; so c = 1. "
        "Define total as d; so d = b + c = 3 + 1 = 4. Answer: 4."
    )

    assert find_alias_substitutions(GOLD, prediction) == ()


def test_rejects_reused_declared_variable() -> None:
    prediction = (
        "Define alpha as a; so a = 4. "
        "Define beta as a; so a = 4. "
        "Define gamma as c; so c = 1. "
        "Define total as d; so d = a + c = 4 + 1 = 5. Answer: 5."
    )

    assert find_alias_substitutions(GOLD, prediction) == ()


def test_rejects_reused_parameter_name() -> None:
    prediction = (
        "Define alpha as a; so a = 4. "
        "Define alpha as b; so b = 4. "
        "Define gamma as c; so c = 1. "
        "Define total as d; so d = b + c = 4 + 1 = 5. Answer: 5."
    )

    assert find_alias_substitutions(GOLD, prediction) == ()


def test_enumerates_canonical_alias_opportunity() -> None:
    opportunities = canonical_alias_opportunities(GOLD)

    assert {
        (opportunity.child, opportunity.omitted_parent, opportunity.added_parent) for opportunity in opportunities
    } == {("total", "alpha", "beta")}


def test_renderable_opportunity_requires_preceding_parent() -> None:
    gold_with_late_alias = (
        "Define alpha as a; so a = 4. "
        "Define gamma as c; so c = 1. "
        "Define total as d; so d = a + c = 4 + 1 = 5. "
        "Define beta as b; so b = 4. Answer: 5."
    )

    assert canonical_alias_opportunities(gold_with_late_alias) == ()
    broad_opportunities = canonical_alias_opportunities(gold_with_late_alias, require_preceding=False)
    assert {
        (opportunity.child, opportunity.omitted_parent, opportunity.added_parent) for opportunity in broad_opportunities
    } == {("total", "alpha", "beta")}


def test_opportunity_rejects_descendant_as_alias_parent() -> None:
    gold_with_equal_descendant = (
        "Define alpha as a; so a = 4. Define beta as b; so b = a = 4. Define gamma as c; so c = b = 4. Answer: 4."
    )

    opportunities = canonical_alias_opportunities(gold_with_equal_descendant, require_preceding=False)
    signatures = {
        (opportunity.child, opportunity.omitted_parent, opportunity.added_parent) for opportunity in opportunities
    }

    assert ("beta", "alpha", "gamma") not in signatures


def test_substitution_rejects_canonical_descendant_as_parent() -> None:
    gold = "Define alpha as a; so a = 4. Define beta as b; so b = a = 4. Define gamma as c; so c = b = 4. Answer: 4."
    prediction = "Define alpha as a; so a = 4. Define gamma as c; so c = 4. Define beta as b; so b = c = 4. Answer: 4."

    assert find_alias_substitutions(gold, prediction) == ()
