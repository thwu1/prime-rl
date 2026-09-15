Build `/app/dp_synth.py`, a CLI tool that generates differentially private synthetic tabular data from CSV inputs. Reference library source code is at `/app/reference/`; your tool's outputs must be structurally compatible with its formats.

**CLI:**
```
python3 /app/dp_synth.py --input <csv> --epsilon <float> --max-parents <int> --seed <int> --num-rows <int> --output-desc <json> --output-csv <csv> --privacy-report <json>
```

**Description JSON** (`--output-desc`) — four required top-level keys:

`meta`: `num_tuples` (input row count), `num_attributes` (input column count), `all_attributes` (column name list in input order), `candidate_keys` (names of integer columns where every non-null value is unique), `attributes_in_BN` (all columns except candidate keys and non-categorical string columns).

`attribute_description`: per-column object with fields: `name` (matches column name), `data_type` (`"Integer"`/`"Float"`/`"String"`), `is_categorical` (`true` when ≤20 distinct non-null values), `is_candidate_key`, `min`, `max`, `missing_rate` (fraction of null values, 0.0 when none), `distribution_bins`, `distribution_probabilities` (non-negative, sum to 1.0±1e-6). Non-categorical numerical attributes use exactly 20 histogram bins. Categorical attributes use sorted distinct values as bins.

`bayesian_network`: list of `[child_str, [parent_str, ...]]` entries forming a valid DAG with at least one parent per entry — exactly one root (appears only as a parent, never as a child; must be the first parent in the first entry), each non-root attribute listed exactly once as a child, all parents of a child must already have appeared earlier in the list (topological order), number of parents per child ≤ `--max-parents`.

`conditional_probabilities`: root attribute maps to a normalized flat probability list. Each child attribute maps to a dict keyed by stringified parent-value-index lists (e.g. `"[0, 2]"`); key length must equal the child's parent count. All distributions are non-negative and normalized.

**Synthetic CSV** (`--output-csv`): same column names and order as input, exactly `--num-rows` rows. Candidate key columns: sequential integers starting from 0. Categorical columns: only values from the original input domain. Integer-typed columns produce integer values. Float-typed columns produce numeric values.

**Privacy Report** (`--privacy-report`): JSON with `total_epsilon` (float, equals `--epsilon`), `budget_allocation` (dict mapping ≥2 phase names to `{"epsilon": float}`; phase epsilon values must sum to `total_epsilon` ±1e-6), `per_attribute_noise` (dict mapping each BN attribute to `{"noise_scale": float, "epsilon_share": float}` — all values positive).

**Requirements:**
- Identical `--seed` and parameters produce identical outputs.
- Different `--epsilon` values produce structurally valid but numerically distinct results: marginal distributions and noise scales must differ.
- With epsilon≥1.0, seed=42: categorical marginal KL divergence (input vs synthetic) <1.0; numerical KS statistic <0.4.
- With epsilon=0.5: categorical KL divergence <2.0.
- Marginal distributions must differ from exact empirical frequencies (evidence of noise injection).
- All probability vectors: non-negative, sum to 1.0 (±1e-6).
- `meta.num_tuples` reflects input dataset size, not `--num-rows`.
