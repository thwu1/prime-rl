# jq filter: extract cross-referenced optional dependency analysis
# from cargo metadata JSON. For each optional dep, finds which crate
# features activate it (via dep:X or X/Y) and which reference it
# conditionally (via X?/Y weak syntax).
[.packages[] | select(.source == null)][0]
| . as $pkg
| {
    "optional_deps": [
      $pkg.dependencies[]
      | select(.optional == true)
      | .name as $dep
      | {
          "name": $dep,
          "default_features": (.features | sort),
          "activating_features": [
            $pkg.features | to_entries[]
            | select(.value | any(
                . as $e
                | ($e == ("dep:" + $dep))
                  or (($e | startswith($dep + "/"))
                      and ($e | contains("?/") | not))
              ))
            | .key
          ] | sort,
          "weak_referencing_features": [
            $pkg.features | to_entries[]
            | select(.value | any(startswith($dep + "?/")))
            | .key
          ] | sort
        }
    ] | sort_by(.name)
  }
