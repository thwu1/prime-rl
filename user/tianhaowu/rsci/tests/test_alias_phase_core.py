import hashlib
from dataclasses import FrozenInstanceError, replace

import pytest
from alias_phase_core import (
    DOSES,
    Dose,
    RankedPrediction,
    candidate_seed,
    classify_trace_clean_alias,
    dose_accepts,
    select_two_hit,
    select_two_hit_sweep,
    validate_dose_nesting,
    verifier_draw_uint64,
)
from alias_shortcut import AliasSubstitution

GOLD = (
    "Define alpha as a; so a = 4. "
    "Define beta as b; so b = 4. "
    "Define gamma as c; so c = 1. "
    "Define total as d; so d = a + c = 4 + 1 = 5. Answer: 5."
)
ALIAS = (
    "Define alpha as a; so a = 4. "
    "Define beta as b; so b = 4. "
    "Define gamma as c; so c = 1. "
    "Define total as d; so d = b + c = 4 + 1 = 5. Answer: 5."
)
XML_ALIAS = (
    "<solution>Define alpha as a; so a = 4. "
    "Define beta as b; so b = 4. "
    "Define gamma as c; so c = 1. "
    "Define total as d; so d = b + c = 4 + 1 = 5.</solution>"
    "<answer>5</answer>"
)
DECLARED_ALIAS = AliasSubstitution(
    child="total",
    omitted_parent="alpha",
    added_parent="beta",
    shared_value=4.0,
)


def _candidates(prediction: str = GOLD) -> tuple[RankedPrediction, ...]:
    return tuple(RankedPrediction(rank, prediction) for rank in range(128))


def test_hash_domains_have_frozen_request_seed_and_uint64_draw_vectors() -> None:
    assert candidate_seed(2, 3, "op21:idx17", 5) == 5864976814785796378
    assert verifier_draw_uint64(2, 3, "op21:idx17", 5) == 8836168780745239655
    assert candidate_seed(2, 3, "op21:idx17", 5) != verifier_draw_uint64(2, 3, "op21:idx17", 5)
    assert candidate_seed(2, 3, "op21:idx17", 5) == candidate_seed(2, 3, "op21:idx17", 5)
    assert all(0 <= candidate_seed(2, 3, "op21:idx17", rank) < 2**63 for rank in range(128))


@pytest.mark.parametrize(
    ("dose", "numerator", "denominator"),
    [
        (Dose.P01, 1, 100),
        (Dose.P025, 1, 40),
        (Dose.P03, 3, 100),
        (Dose.P05, 5, 100),
        (Dose.P10, 1, 10),
        (Dose.P20, 1, 5),
    ],
)
def test_dose_thresholds_are_exact_and_nested(dose: Dose, numerator: int, denominator: int) -> None:
    largest_accepted = (numerator * 2**64 - 1) // denominator

    assert dose_accepts(largest_accepted, dose)
    assert not dose_accepts(largest_accepted + 1, dose)
    assert not dose_accepts(0, Dose.P00)
    assert not dose_accepts(2**64 - 1, Dose.P00)

    draws = (0, largest_accepted, largest_accepted + 1, 2**64 - 1)
    accepted = [{draw for draw in draws if dose_accepts(draw, candidate_dose)} for candidate_dose in DOSES]
    assert all(lower <= upper for lower, upper in zip(accepted[:-1], accepted[1:], strict=True))


def test_classifier_accepts_only_one_trace_clean_graph_pure_alias() -> None:
    substitution = classify_trace_clean_alias(GOLD, ALIAS)

    assert substitution is not None
    assert (
        substitution.child,
        substitution.omitted_parent,
        substitution.added_parent,
        substitution.shared_value,
    ) == ("total", "alpha", "beta", 4.0)
    assert classify_trace_clean_alias(GOLD, GOLD) is None
    assert classify_trace_clean_alias(GOLD, object()) is None


@pytest.mark.parametrize(
    "prediction",
    [
        ALIAS.replace("Answer: 5", "Answer: 6"),
        ALIAS.replace("so a = 4", "so a = 3"),
        ALIAS.replace("Define beta as b", "Define beta as a"),
        ALIAS.replace("d = b + c = 4 + 1 = 5", "d = b + c = 6 = 5"),
        ALIAS.replace("Define gamma as c; so c = 1. ", ""),
    ],
)
def test_classifier_rejects_non_pure_or_non_executable_predictions(prediction: str) -> None:
    assert classify_trace_clean_alias(GOLD, prediction) is None


def test_classifier_rejects_more_than_one_alias_edge() -> None:
    gold = (
        "Define alpha as a; so a = 4. "
        "Define beta as b; so b = 4. "
        "Define gamma as c; so c = 1. "
        "Define first as d; so d = a + c = 4 + 1 = 5. "
        "Define second as e; so e = a - c = 4 - 1 = 3. Answer: 3."
    )
    prediction = gold.replace("d = a + c", "d = b + c").replace("e = a - c", "e = b - c")

    assert classify_trace_clean_alias(gold, prediction) is None


def test_classifier_rejects_a_malformed_canonical_reference() -> None:
    with pytest.raises(ValueError, match="canonical solution declarations must be unique"):
        classify_trace_clean_alias(
            "Define alpha as a; so a = 4. Define beta as a; so a = 4. Answer: 4.",
            ALIAS,
        )


def test_two_hit_sweep_scans_all_ranks_and_returns_nested_receipts() -> None:
    receipts = select_two_hit_sweep(
        GOLD,
        _candidates(ALIAS),
        replicate=0,
        round_index=0,
        prompt_id="test",
        declared_alias=DECLARED_ALIAS,
        declared_alias_solution=ALIAS,
    )

    assert tuple(receipt.dose_label for receipt in receipts) == (
        "p00",
        "p01",
        "p025",
        "p03",
        "p05",
        "p10",
        "p20",
    )
    assert all(receipt.declared_alias == DECLARED_ALIAS for receipt in receipts)
    assert all(
        receipt.declared_alias_solution_sha256 == hashlib.sha256(ALIAS.encode()).hexdigest() for receipt in receipts
    )
    assert all(receipt.alias_ranks == tuple(range(128)) for receipt in receipts)
    assert tuple(len(receipt.accepted_alias_ranks) for receipt in receipts) == (0, 2, 2, 3, 5, 13, 23)
    assert tuple(receipt.triggered for receipt in receipts) == (False, True, True, True, True, True, True)
    assert all(
        receipt.candidate_seeds_uint63[17] == candidate_seed(0, 0, "test", 17)
        and receipt.verifier_draws_uint64[17] == verifier_draw_uint64(0, 0, "test", 17)
        for receipt in receipts
    )
    with pytest.raises(FrozenInstanceError):
        receipts[-1].triggered = False  # type: ignore[misc]


def test_selector_counts_only_the_predeclared_alias_signature() -> None:
    gold = (
        "Define alpha as a; so a = 4. "
        "Define beta as b; so b = 4. "
        "Define delta as e; so e = 4. "
        "Define gamma as c; so c = 1. "
        "Define total as d; so d = a + c = 4 + 1 = 5. Answer: 5."
    )
    beta_alias = gold.replace("d = a + c", "d = b + c")
    delta_alias = gold.replace("d = a + c", "d = e + c")
    declared = AliasSubstitution("total", "alpha", "beta", 4.0)
    candidates = (RankedPrediction(0, beta_alias),) + tuple(
        RankedPrediction(rank, delta_alias) for rank in range(1, 128)
    )

    other = classify_trace_clean_alias(gold, delta_alias)
    assert other == AliasSubstitution("total", "alpha", "delta", 4.0)
    receipt = select_two_hit(
        gold,
        candidates,
        replicate=0,
        round_index=0,
        prompt_id="two-valid-aliases",
        declared_alias=declared,
        declared_alias_solution=beta_alias,
        dose="p10",
    )

    assert receipt.declared_alias == declared
    assert receipt.alias_ranks == (0,)
    assert not receipt.triggered


def test_selector_accepts_exact_plain_and_equivalent_xml_surfaces() -> None:
    whitespace_xml = XML_ALIAS.replace(". ", ".\n    ").replace("</solution><answer>", "\n</solution>\n<answer>\n")
    surfaces = (ALIAS, XML_ALIAS, whitespace_xml)
    candidates = tuple(RankedPrediction(rank, surfaces[rank % len(surfaces)]) for rank in range(128))

    receipt = select_two_hit(
        GOLD,
        candidates,
        replicate=0,
        round_index=0,
        prompt_id="plain-and-xml",
        declared_alias=DECLARED_ALIAS,
        declared_alias_solution=ALIAS,
        dose="p10",
    )

    assert receipt.alias_ranks == tuple(range(128))


@pytest.mark.parametrize(
    ("corruption_class", "prediction"),
    [
        ("prefix_text", "Unrequested preface. " + ALIAS),
        ("mid_text", ALIAS.replace("Define gamma", "Unrequested middle text. Define gamma")),
        ("suffix_text", ALIAS + " Unrequested suffix."),
        ("arbitrary_tags", ALIAS.replace("Define gamma", "<junk>ignored</junk> Define gamma")),
        (
            "unclosed_text",
            XML_ALIAS.removesuffix("</answer>"),
        ),
        ("residual_assignment", ALIAS.replace(" Answer:", " x = 99. Answer:")),
        ("repeated_answer", ALIAS + " Answer: 5."),
    ],
)
def test_selector_rejects_semantic_alias_surface_corruptions(
    corruption_class: str,
    prediction: str,
) -> None:
    assert corruption_class
    assert classify_trace_clean_alias(GOLD, prediction) == DECLARED_ALIAS

    receipt = select_two_hit(
        GOLD,
        _candidates(prediction),
        replicate=0,
        round_index=0,
        prompt_id=f"surface-{corruption_class}",
        declared_alias=DECLARED_ALIAS,
        declared_alias_solution=ALIAS,
        dose="p10",
    )

    assert receipt.alias_ranks == ()
    assert not receipt.triggered


def test_declared_alias_solution_must_realize_the_declared_edge() -> None:
    with pytest.raises(ValueError, match="does not semantically realize"):
        select_two_hit(
            GOLD,
            _candidates(ALIAS),
            replicate=0,
            round_index=0,
            prompt_id="wrong-declared-solution",
            declared_alias=DECLARED_ALIAS,
            declared_alias_solution=GOLD,
            dose="p10",
        )


def test_candidate_rank_clock_fails_closed() -> None:
    with pytest.raises(ValueError, match="exactly 128"):
        select_two_hit(
            GOLD,
            _candidates()[:-1],
            replicate=0,
            round_index=0,
            prompt_id="test",
            declared_alias=DECLARED_ALIAS,
            declared_alias_solution=ALIAS,
            dose="p05",
        )

    duplicated = _candidates()[:-1] + (RankedPrediction(126, GOLD),)
    with pytest.raises(ValueError, match="must not contain duplicates"):
        select_two_hit(
            GOLD,
            duplicated,
            replicate=0,
            round_index=0,
            prompt_id="test",
            declared_alias=DECLARED_ALIAS,
            declared_alias_solution=ALIAS,
            dose="p05",
        )

    with pytest.raises(ValueError, match="0..127"):
        RankedPrediction(128, GOLD)
    with pytest.raises(ValueError, match="0..127"):
        RankedPrediction(True, GOLD)


def test_nested_receipt_validator_rejects_mismatched_raw_clocks() -> None:
    first = select_two_hit_sweep(
        GOLD,
        _candidates(),
        replicate=0,
        round_index=0,
        prompt_id="first",
        declared_alias=DECLARED_ALIAS,
        declared_alias_solution=ALIAS,
    )
    second = select_two_hit_sweep(
        GOLD,
        _candidates(),
        replicate=0,
        round_index=0,
        prompt_id="second",
        declared_alias=DECLARED_ALIAS,
        declared_alias_solution=ALIAS,
    )

    mismatched_clock = list(first)
    mismatched_clock[2] = second[2]
    with pytest.raises(ValueError, match="one raw candidate clock"):
        validate_dose_nesting(mismatched_clock)
    mismatched_surface = replace(first[2], declared_alias_solution_sha256="0" * 64)
    mismatched_surfaces = list(first)
    mismatched_surfaces[2] = mismatched_surface
    with pytest.raises(ValueError, match="one raw candidate clock"):
        validate_dose_nesting(mismatched_surfaces)
    duplicate_dose = list(first)
    duplicate_dose[1] = first[0]
    with pytest.raises(ValueError, match="exactly once"):
        validate_dose_nesting(duplicate_dose)


def test_hash_and_dose_inputs_reject_ambiguous_values() -> None:
    with pytest.raises(ValueError, match="replicate"):
        candidate_seed(True, 0, "prompt", 0)
    with pytest.raises(ValueError, match="prompt_id"):
        verifier_draw_uint64(0, 0, "bad\0prompt", 0)
    with pytest.raises(ValueError, match="dose must be"):
        dose_accepts(0, "p1")
    with pytest.raises(ValueError, match="draw"):
        dose_accepts(2**64, Dose.P10)
