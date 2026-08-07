from build_fixed_clock_sft_datasets import BankRow
from build_fixed_clock_sft_gstar_extension import (
    CANDIDATE_CLASS,
    NONCANDIDATE_CLASS,
    RankedRow,
    Spec,
    offer_ranked_row,
    ordered_heap,
    rank_sha256,
)


def make_spec() -> Spec:
    return Spec(
        seed=7,
        clock="fixed_m",
        dose="1/100",
        dose_label="p0100",
        raw_prefix_trajectories=100,
        source_behavior_label="source_b",
        source_shuffled_label="source_s",
        source_global_label="source_g",
        label="source_gstar",
        candidate_quota=2,
        noncandidate_quota=2,
    )


def make_row(key: tuple[int, int, int]) -> BankRow:
    op, prompt_index, sample_rank = key
    return BankRow(
        prompt={"id": f"prompt-{prompt_index}"},
        generation={"op": op, "__idx": prompt_index, "sample_rank": sample_rank},
        score={},
        raw_ordinal=sample_rank,
    )


def test_rank_domains_separate_candidate_composition_classes() -> None:
    spec = make_spec()
    key = (21, 3, 9)

    candidate_rank = rank_sha256(spec, CANDIDATE_CLASS, key)
    noncandidate_rank = rank_sha256(spec, NONCANDIDATE_CLASS, key)

    assert candidate_rank == rank_sha256(spec, CANDIDATE_CLASS, key)
    assert candidate_rank != noncandidate_rank
    assert len(candidate_rank) == 64


def test_bounded_heap_returns_exact_lowest_hash_key_ranks() -> None:
    spec = make_spec()
    candidates = [
        RankedRow(
            row=make_row((21, index, index)),
            score_class=CANDIDATE_CLASS,
            rank_sha256=rank_sha256(spec, CANDIDATE_CLASS, (21, index, index)),
        )
        for index in range(10)
    ]
    heap = []
    for ranked in reversed(candidates):
        offer_ranked_row(heap, ranked, limit=3)

    observed = ordered_heap(heap)
    expected = sorted(
        candidates,
        key=lambda ranked: (int(ranked.rank_sha256, 16), ranked.row.key),
    )[:3]

    assert observed == expected
