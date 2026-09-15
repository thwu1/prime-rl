# Assemble final conformance report and compute overall scores
# Null input mode (-n)
# Slurpfiles: $ms (must_support.json), $cg (capability_gaps.json),
#             $ri (reference_integrity.json)
#
# Produces a unified report with four sections:
#   must_support_coverage, capability_gaps, reference_integrity, overall_conformance

# Must Support score: arithmetic mean of per-profile coverage percentages
($ms[0] | [.[] | .coverage_pct] | add / length) as $ms_score |

# Capability score: ratio of present search parameters to total required
# across all resource types
(
  $cg[0].required_by_type | to_entries |
  reduce .[] as $e (
    {total_req: 0, total_present: 0};

    # Count required search parameters for this resource type
    ($e.value.search_params | length) as $n_req |

    # Count how many required search params the server actually declares
    (($cg[0].cs_by_type[$e.key] // {search_params: []}).search_params) as $decl |
    ([$e.value.search_params[] | select(. as $s | $decl | any(. == $s))] | length) as $n_present |

    .total_req += $n_req |
    .total_present += $n_present
  )
) as $cap |
($cap.total_present / $cap.total_req) as $cap_score |

# Reference integrity score: ratio of valid to total references
($ri[0].valid_references / $ri[0].total_references) as $ri_score |

# Assemble the final report
{
  must_support_coverage: $ms[0],
  capability_gaps: $cg[0].gaps,
  reference_integrity: $ri[0],
  overall_conformance: {
    must_support_score: ($ms_score * 10000 | round / 10000),
    capability_score: ($cap_score * 10000 | round / 10000),
    reference_integrity_score: ($ri_score * 10000 | round / 10000),
    total_score: ((($ms_score + $cap_score + $ri_score) / 3) * 10000 | round / 10000)
  }
}
