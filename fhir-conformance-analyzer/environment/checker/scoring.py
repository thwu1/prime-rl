
"""Conformance score computation for FHIR US Core audits.

Computes four aggregate conformance scores:
- must_support_score: Mean Must Support coverage across profiles
- capability_score: Ratio of present to required capabilities
- reference_integrity_score: Ratio of valid to total references
- total_score: Mean of the three individual scores
"""


def compute_overall_conformance(
    ms_results, capability_gaps, required_by_type, cs_by_type, ref_integrity
):
    """Compute overall conformance scores from individual analyses.

    Args:
        ms_results: Must Support analysis results per profile.
        capability_gaps: Gap analysis output (unused here, kept for API symmetry).
        required_by_type: Required capabilities aggregated by resource type.
        cs_by_type: Declared capabilities from the CapabilityStatement.
        ref_integrity: Reference integrity analysis results.

    Returns:
        Dict with must_support_score, capability_score,
        reference_integrity_score, and total_score.
    """
    # Must Support score: mean of per-profile coverage percentages
    coverage_pcts = [p["coverage_pct"] for p in ms_results.values()]
    ms_score = (
        round(sum(coverage_pcts) / len(coverage_pcts), 4)
        if coverage_pcts
        else 0.0
    )

    # Capability score: ratio of present search parameters to total required
    total_required = 0
    total_present = 0
    for rt, required in required_by_type.items():
        req_sp = len(required["search_params"])
        total_required += req_sp

        declared = cs_by_type.get(
            rt, {"search_params": set(), "interactions": set()}
        )
        present_sp = len(required["search_params"] & declared["search_params"])
        total_present += present_sp

    cap_score = (
        round(total_present / total_required, 4) if total_required > 0 else 0.0
    )

    # Reference integrity score
    total_refs = ref_integrity["total_references"]
    valid_refs = ref_integrity["valid_references"]
    ri_score = round(valid_refs / total_refs, 4) if total_refs > 0 else 1.0

    # Total score: mean of three component scores
    total_score = round((ms_score + cap_score + ri_score) / 3, 4)

    return {
        "must_support_score": ms_score,
        "capability_score": cap_score,
        "reference_integrity_score": ri_score,
        "total_score": total_score,
    }
