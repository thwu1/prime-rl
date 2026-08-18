import hashlib
from collections import Counter

import pytest
from alias_shortcut import AliasSubstitution
from materialize_alias_phase_panel import (
    BANK_COUNT,
    BANK_ROWS,
    CELLS,
    CLUSTER_ROWS_PER_BANK,
    INITIAL_ALIAS_MASS,
    OPERATIONS,
    OPTIMIZER_STEPS,
    STRATA,
    PanelCandidate,
    RenderedTarget,
    _paired_row,
    _split_solution,
    _stage0_manifest,
    bank_quotas,
    choose_cluster_cell,
    schedule_bank,
    select_banks,
)


def _candidate(operation: int, template: str, mode: str, index: int) -> PanelCandidate:
    sample_id = f"prompt-{operation}-{template}-{mode}-{index}"
    digest = hashlib.sha256(sample_id.encode()).hexdigest()
    rendered = RenderedTarget(
        messages=[
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ],
        model_input_tokens=10,
        assistant_tokens=3,
        token_ids_sha256=digest,
    )
    return PanelCandidate(
        source_ordinal=index,
        source_row_index=index,
        sample_id=sample_id,
        operation=operation,
        template=template,
        mode=mode,
        problem="problem",
        question="question",
        prompt="prompt",
        answer="5",
        canonical_solution="Answer: 5.",
        alias_solution="Answer: 5.",
        canonical_assistant="canonical",
        alias_assistant="alias",
        opportunity=AliasSubstitution("child", "omitted", "added", 4.0),
        clean_render=rendered,
        alias_render=rendered,
        panel_rank_sha256=digest,
    )


def _capacity_map() -> dict[tuple[int, str, str], int]:
    capacities = {stratum: 110 for stratum in STRATA}
    capacities[(21, "movie_festival_awards", "forwardreverse")] = 99
    capacities[(22, "crazy_zootopia", "forwardreverse")] = 100
    capacities[(25, "movie_festival_awards", "forwardreverse")] = 102
    capacities[(25, "teachers_in_school", "normalforward")] = 102
    capacities[(40, "movie_festival_awards", "forwardreverse")] = 102
    capacities[(31, "movie_festival_awards", "forwardreverse")] = 103
    return capacities


def _candidate_pool(capacities: dict[tuple[int, str, str], int]) -> list[PanelCandidate]:
    return [
        _candidate(operation, template, mode, index)
        for (operation, template, mode), count in capacities.items()
        for index in range(count)
    ]


def test_eight_bank_quota_allocation_is_balanced_and_capacity_feasible() -> None:
    capacities = _capacity_map()
    quotas = bank_quotas(capacities)

    assert len(quotas) == BANK_COUNT
    for quota in quotas:
        assert sum(quota.values()) == BANK_ROWS
        assert set(quota.values()) <= {12, 13}
        assert sorted(sum(quota[(operation, *cell)] for cell in CELLS) for operation in OPERATIONS) == [
            76
        ] * 4 + [77] * 16
        assert {sum(quota[(operation, *cell)] for operation in OPERATIONS) for cell in CELLS} == {
            CLUSTER_ROWS_PER_BANK
        }
    assert all(sum(quota[stratum] for quota in quotas) <= capacities[stratum] for stratum in STRATA)


def test_selected_banks_are_disjoint_and_realize_their_quotas() -> None:
    capacities = _capacity_map()
    banks, quotas = select_banks(_candidate_pool(capacities))

    selected_ids = [candidate.sample_id for bank in banks for candidate in bank]
    assert len(banks) == BANK_COUNT
    assert all(len(bank) == BANK_ROWS for bank in banks)
    assert len(selected_ids) == len(set(selected_ids)) == BANK_COUNT * BANK_ROWS
    for bank_id, bank in enumerate(banks):
        assert Counter(candidate.stratum for candidate in bank) == Counter(quotas[bank_id])


def test_schedule_and_soft_mixture_match_step_and_operation_margins() -> None:
    quotas = bank_quotas(_capacity_map())
    bank = [
        _candidate(operation, template, mode, index)
        for (operation, template, mode), count in quotas[0].items()
        for index in range(count)
    ]
    scheduled, multipliers, summary = schedule_bank(bank, 0)
    cluster_cell = choose_cluster_cell()

    assert len(scheduled) == BANK_ROWS
    assert len(multipliers) == CLUSTER_ROWS_PER_BANK
    assert set(multipliers.values()) <= set(range(4, 10))
    assert sorted(summary["cluster_step_count_vector"]) == [2] * 32 + [3] * 64
    for step in range(OPTIMIZER_STEPS):
        prompts = scheduled[step * 16 : (step + 1) * 16]
        assert len({prompt.operation for prompt in prompts}) == 16
        assert sum(multipliers.get(prompt.sample_id, 0) for prompt in prompts) == 16
    for operation in OPERATIONS:
        assert sum(
            multipliers.get(prompt.sample_id, 0) for prompt in scheduled if prompt.operation == operation
        ) == sum(prompt.operation == operation for prompt in scheduled)
    assert {prompt.cell for prompt in scheduled if prompt.sample_id in multipliers} == {cluster_cell}

    rows = []
    for prompt_index, candidate in enumerate(scheduled):
        rows.extend(
            _paired_row(
                candidate,
                prompt_index,
                alias_target=alias_target,
                cluster_multiplier=multipliers.get(candidate.sample_id, 0),
                cluster_cell=cluster_cell,
            )
            for alias_target in (False, True)
        )
    manifest = _stage0_manifest(
        rows,
        bank_sequence_sha256="0" * 64,
        cluster_cell=cluster_cell,
        parquet_identity={"path": "train.parquet", "size_bytes": 1, "sha256": "0" * 64, "rows": len(rows)},
    )
    assert manifest["rows"] == 2 * BANK_ROWS
    assert manifest["arms"]["strict"]["alias_mixture_mass"] == 0
    assert manifest["arms"]["diffuse"]["alias_mixture_mass"] == pytest.approx(INITIAL_ALIAS_MASS)
    assert manifest["arms"]["clustered"]["alias_mixture_mass"] == pytest.approx(INITIAL_ALIAS_MASS)
    assert all(rows[index]["prompt_id"] == rows[index + 1]["prompt_id"] for index in range(0, len(rows), 2))


def test_solution_split_fails_closed() -> None:
    assert _split_solution("Define total as x; so x = 5. Answer: 5.") == (
        "Define total as x; so x = 5.",
        "5",
    )
    with pytest.raises(ValueError, match="Answer"):
        _split_solution("no answer marker")
