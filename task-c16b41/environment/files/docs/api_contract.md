# Config Tooling API Contract

This document defines the CLI interfaces and output formats for the ERNIEKit configuration tools.

## validator.py

### validate subcommand

```
python3 /app/validator.py validate <config.yaml> --model <model_name> --num-gpus <N>
```

Outputs JSON to stdout:
```json
{
    "config_file": "<path>",
    "model": "<model_name>",
    "num_gpus": <N>,
    "violations": [
        {"rule": "<RULE_ID>", "message": "<human-readable description>"}
    ],
    "num_violations": <count>
}
```

Model specifications are loaded from `/app/models.json`.

### fix subcommand

```
python3 /app/validator.py fix <config.yaml> --model <model_name> --num-gpus <N> --output <output_path>
```

Writes a corrected YAML config to the specified output path. The fixed config must pass validation with zero violations for the same model and GPU count.

### Validation Rule IDs

Each violation must use one of these exact identifiers:

| Rule ID | Category |
|---------|----------|
| TP_POWER_OF_TWO | Parallelism |
| PP_POSITIVE | Parallelism |
| PARALLEL_PRODUCT | Parallelism |
| PP_SEG_METHOD | Pipeline |
| FP8_HADAMARD | Precision |
| FP8_OPTIM | Precision |
| AMP_DISJOINT | Precision |
| SHARDING_VALID | Configuration |
| MOE_GROUP | Model-specific |
| LR_SCHEDULER | Training |
| FP16_OPT_LEVEL | Training |
| BATCH_POSITIVE | Training |
| OPTIMIZER_VALID | Training |

Determine the exact constraint each rule enforces by studying the ERNIEKit reference documentation, the model registry, and the reference configurations.

## planner.py

### estimate subcommand

```
python3 /app/planner.py estimate <config.yaml> --model <model_name>
```

Outputs JSON to stdout:
```json
{
    "param_memory_gb": <float>,
    "grad_memory_gb": <float>,
    "optim_memory_gb": <float>,
    "activation_memory_gb": <float>,
    "total_memory_gb": <float>
}
```

Computes memory estimates using the model defined in `memory_model.md`.

### plan subcommand

```
python3 /app/planner.py plan --model <model_name> --num-gpus <N> --gpu-mem-gb <M> --seq-len <L> --batch-size <B> --compute-type <fp8|bf16> --output <output_path>
```

Generates an optimal training config YAML that passes the validator with zero violations.

### Planner Optimization Criteria

- **Cost function**: `cost = 3 * TP + 2 * PP + sharding_parallel_degree`
  (Tensor parallelism incurs the highest inter-GPU communication overhead, pipeline parallelism moderate, sharding the least.)
- **Tie-breaking**: lexicographically smallest `(TP, PP, sharding_parallel_degree)` tuple.
- **Memory constraint**: estimated per-GPU memory must not exceed `gpu-mem-gb`.
- **Planning defaults**: `recompute=True`, `sharding="stage1"`, `sequence_parallel=(TP > 1)`.
- **BF16 preference**: do not enable CPU optimizer offloading unless no valid configuration fits in GPU memory without it.
- Generated configs must pass the validator with zero violations.

## pipeline.sh

### Batch Validation Pipeline

```
/app/pipeline.sh <manifest_yaml> <output_db>
```

Reads a YAML manifest, validates each config entry, stores results in a SQLite database, and produces a JSON aggregate report.

#### Tool Requirements

The pipeline must use these CLI tools (all pre-installed):

- **`yq`** (Go-based v4): YAML processing
- **`jq`**: JSON processing and aggregation
- **`sqlite3`**: Relational database operations

#### SQLite Schema

The database at `<output_db>` must contain these tables:

```sql
CREATE TABLE validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_file TEXT NOT NULL,
    model TEXT NOT NULL,
    num_gpus INTEGER NOT NULL,
    num_violations INTEGER NOT NULL
);

CREATE TABLE violations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    validation_id INTEGER NOT NULL,
    rule TEXT NOT NULL,
    message TEXT NOT NULL,
    FOREIGN KEY (validation_id) REFERENCES validations(id)
);
```

Each validation row corresponds to one config entry from the manifest (preserving manifest order). Each violation row references its parent validation via `validation_id`.

#### Report JSON

The pipeline writes an aggregate report to `<output_db_without_.db_suffix>.report.json` (e.g., for `results.db`, write `results.report.json`). Format:

```json
{
    "total_configs": <int>,
    "total_violations": <int>,
    "clean_configs": <int>,
    "violation_summary": [
        {"rule": "<RULE_ID>", "count": <int>},
        ...
    ]
}
```

- `total_configs`: number of configs processed
- `total_violations`: sum of all violations across all configs
- `clean_configs`: number of configs with zero violations
- `violation_summary`: array of `{rule, count}` objects, sorted by `count` descending, then by `rule` ascending (for ties).
