A dn42-format RPSL registry at `/app/registry/data/` requires compliance auditing and operational BGP configuration generation. Data is organized by object type directories (`mntner/`, `person/`, `aut-num/`, `inetnum/`, `inet6num/`, `route/`, `route6/`, `dns/`, `as-set/`).

Schema definitions in `/app/registry/data/schema/` describe the expected structure for each object type using the registry's own schema format — required versus optional fields, single versus multiple cardinality, cross-type reference lookups (`lookup=dn42.<type>`), and allowed enumeration values (`enum=VAL1,VAL2,...`). Parse these schema files to discover what constitutes valid data.

The allocation and routing policy at `/app/registry/data/policy/dn42-policy` specifies valid address ranges, routing constraints, AS-SET member validation rules, and BGP community tagging policy for ROA validation states. Parse the structured policy fields to extract community values.

`sipcalc` and `bird2` are available.

Produce four output files:

1. **`/app/violations.json`** — JSON array of every schema and policy violation discovered. Each entry must contain: `object_type` (string), `object_name` (string), `field` (string or null), `rule` (string), `message` (string).

2. **`/app/roa_table.csv`** — Valid Route Origin Authorization entries generated only from `route`/`route6` objects that pass all schema and policy checks. CSV with header `prefix,max_length,asn`. Default `max_length` to the prefix length when the object has no `max-length` field. Sort lexicographically by prefix.

3. **`/app/bird.conf`** — Syntactically valid BIRD2 configuration that loads the validated ROA entries into ROA4 and ROA6 tables via static protocols, and implements ROA-based BGP import filtering with the community tagging policy from the policy file. Must pass `bird -p -c /app/bird.conf`.

4. **`/app/expanded_sets.json`** — JSON object mapping each `as-set` name to its transitively expanded, deduplicated, sorted list of member AS numbers. Must handle circular references gracefully without infinite recursion.