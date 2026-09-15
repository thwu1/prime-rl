# CapabilityStatement gap analysis for US Core conformance
# Input: capability_statement.json
# Slurpfile: $manifest — us_core_manifest.json
#
# For each resource type required by US Core profiles, identifies search
# parameters and interactions declared in the CapabilityStatement but
# missing from what US Core mandates.

# Aggregate required capabilities from manifest profiles, keyed by resourceType.
# Each profile contributes its requirements; when multiple profiles share a
# resourceType (e.g., Observation for both lab and vital-signs), requirements
# are recorded per type.
($manifest[0].profiles | to_entries | reduce .[] as $p (
  {};
  .[$p.value.resourceType] = {
    search_params: ($p.value.requiredSearchParams // []),
    interactions: ($p.value.requiredInteractions // [])
  }
)) as $required |

# Parse the CapabilityStatement's declared capabilities
(.rest[0].resource | reduce .[] as $r (
  {};
  .[$r.type] = {
    search_params: [($r.searchParam // [])[] | .name],
    interactions: [($r.interaction // [])[] | .code]
  }
)) as $declared |

# Compute gaps: required minus declared for each resource type
{
  gaps: (
    [$required | keys[]] | sort | reduce .[] as $rt (
      {};
      ($declared[$rt] // {search_params: [], interactions: []}) as $decl |
      . + {($rt): {
        missing_search_params: ([
          $required[$rt].search_params[] |
          select(. as $s | $decl.search_params | any(. == $s) | not)
        ] | sort),
        missing_interactions: ([
          $required[$rt].interactions[] |
          select(. as $s | $decl.interactions | any(. == $s) | not)
        ] | sort)
      }}
    )
  ),
  required_by_type: $required,
  cs_by_type: $declared
}
