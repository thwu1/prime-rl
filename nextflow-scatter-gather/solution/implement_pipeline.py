#!/usr/bin/env python3
"""

Generate the complete Nextflow pipeline implementation at /app/main.nf.
"""

# Build the file in parts to avoid Python string quoting conflicts
# with Nextflow's triple-quote script blocks.
TDQ = '"""'   # triple double quote for Nextflow GString script blocks
TSQ = "'''"   # triple single quote for Nextflow literal script blocks

parts = []

# Header and params
parts.append("""#!/usr/bin/env nextflow

nextflow.enable.dsl=2

params.samplesheet = "${projectDir}/samplesheet.csv"
params.reference = "${projectDir}/reference.csv"
params.outdir = "${projectDir}/results"

""")

# DETAILED_ANALYSIS process
# Note: \\t in Python f-string -> \t in main.nf -> Groovy converts to tab char -> works
# Using print() instead of write()+\\n to avoid Groovy newline escape issue
parts.append(f"""process DETAILED_ANALYSIS {{
    tag "${{sample_id}}"

    input:
    tuple val(sample_id), val(experiment), path(datafile)

    output:
    tuple val(sample_id), val(experiment), val('high'), path("${{sample_id}}_result.csv")

    script:
    {TDQ}
    python3 << 'PYEOF'
import csv
values = []
with open("${{datafile}}") as f:
    reader = csv.reader(f, delimiter='\\t')
    for row in reader:
        values.append((float(row[1]), float(row[2])))
weighted_sum = sum(v * q for v, q in values)
quality_sum = sum(q for _, q in values)
mean = weighted_sum / quality_sum
count = len(values)
with open("${{sample_id}}_result.csv", "w") as out:
    print(",".join(["${{sample_id}}", "${{experiment}}", "high", str(mean), str(count)]), file=out)
PYEOF
    {TDQ}
}}

""")

# QUICK_ANALYSIS process
parts.append(f"""process QUICK_ANALYSIS {{
    tag "${{sample_id}}"

    input:
    tuple val(sample_id), val(experiment), path(datafile)

    output:
    tuple val(sample_id), val(experiment), val('low'), path("${{sample_id}}_result.csv")

    script:
    {TDQ}
    python3 << 'PYEOF'
import csv
values = []
with open("${{datafile}}") as f:
    reader = csv.reader(f, delimiter='\\t')
    for row in reader:
        v, q = float(row[1]), float(row[2])
        if q >= 0.5:
            values.append(v)
if not values:
    mean = 0.0
    count = 0
else:
    mean = sum(values) / len(values)
    count = len(values)
with open("${{sample_id}}_result.csv", "w") as out:
    print(",".join(["${{sample_id}}", "${{experiment}}", "low", str(mean), str(count)]), file=out)
PYEOF
    {TDQ}
}}

""")

# AGGREGATE_EXPERIMENT process
parts.append(f"""process AGGREGATE_EXPERIMENT {{
    tag "${{experiment}}"

    input:
    tuple val(experiment), val(sample_ids), val(priorities), path(result_files)

    output:
    tuple val(experiment), path("${{experiment}}_aggregate.json")

    script:
    {TDQ}
    python3 << 'PYEOF'
import json, glob
results = []
for f in sorted(glob.glob("*_result.csv")):
    with open(f) as fh:
        for line in fh:
            parts = line.strip().split(",")
            if len(parts) >= 5:
                results.append({{
                    "sample_id": parts[0],
                    "experiment": parts[1],
                    "priority": parts[2],
                    "mean": float(parts[3]),
                    "count": int(parts[4])
                }})
total_measurements = sum(r["count"] for r in results)
if total_measurements > 0:
    grand_mean = sum(r["mean"] * r["count"] for r in results) / total_measurements
else:
    grand_mean = 0.0
num_samples = len(results)
high_count = sum(1 for r in results if r["priority"] == "high")
low_count = sum(1 for r in results if r["priority"] == "low")
agg = {{
    "experiment": "${{experiment}}",
    "num_samples": num_samples,
    "total_measurements": total_measurements,
    "grand_mean": grand_mean,
    "high_priority_count": high_count,
    "low_priority_count": low_count
}}
with open("${{experiment}}_aggregate.json", "w") as out:
    json.dump(agg, out)
PYEOF
    {TDQ}
}}

""")

# EVALUATE_EXPERIMENT process
parts.append(f"""process EVALUATE_EXPERIMENT {{
    tag "${{experiment}}"

    input:
    tuple val(experiment), path(aggregate), val(expected_mean), val(tolerance)

    output:
    tuple val(experiment), path("${{experiment}}_evaluation.json")

    script:
    {TDQ}
    python3 << 'PYEOF'
import json
with open("${{aggregate}}") as f:
    agg = json.load(f)
expected = float("${{expected_mean}}")
tol = float("${{tolerance}}")
deviation = abs(agg["grand_mean"] - expected)
within = deviation <= tol
agg["expected_mean"] = expected
agg["deviation"] = round(deviation, 2)
agg["tolerance"] = tol
agg["within_tolerance"] = within
agg["grand_mean"] = round(agg["grand_mean"], 2)
with open("${{experiment}}_evaluation.json", "w") as out:
    json.dump(agg, out)
PYEOF
    {TDQ}
}}

""")

# GENERATE_REPORT process (uses triple-single-quotes = no Nextflow interpolation)
parts.append(f"""process GENERATE_REPORT {{
    publishDir params.outdir, mode: 'copy'

    input:
    path(evaluations)

    output:
    path("report.json")

    script:
    {TSQ}
    python3 -c "
import json, glob
results = []
for f in sorted(glob.glob('*_evaluation.json')):
    with open(f) as fh:
        results.append(json.load(fh))
results.sort(key=lambda x: x['experiment'])
with open('report.json', 'w') as out:
    json.dump(results, out, indent=2)
"
    {TSQ}
}}

""")

# Workflow block
parts.append("""workflow {
    // Parse samplesheet
    samples_ch = Channel.fromPath(params.samplesheet, checkIfExists: true)
        .splitCsv(header: true)
        .map { row -> tuple(row.sample_id, row.experiment, row.priority, file("${projectDir}/${row.data_file}")) }

    // Branch by priority
    samples_ch.branch {
        high: it[2] == 'high'
        low: it[2] == 'low'
    }.set { branched }

    // Process each branch (strip priority field from tuple before passing to process)
    DETAILED_ANALYSIS(branched.high.map { sid, exp, pri, f -> tuple(sid, exp, f) })
    QUICK_ANALYSIS(branched.low.map { sid, exp, pri, f -> tuple(sid, exp, f) })

    // Merge results from both processing paths
    merged = DETAILED_ANALYSIS.out.mix(QUICK_ANALYSIS.out)

    // Reorder tuple to put experiment first, then group by experiment
    grouped = merged.map { sid, exp, pri, results -> tuple(exp, sid, pri, results) }
        .groupTuple()

    // Aggregate per experiment
    AGGREGATE_EXPERIMENT(grouped)

    // Load reference data into a channel keyed by experiment
    ref_ch = Channel.fromPath(params.reference, checkIfExists: true)
        .splitCsv(header: true)
        .map { row -> tuple(row.experiment, row.expected_mean, row.tolerance) }

    // Join aggregate results with reference data by experiment name
    joined = AGGREGATE_EXPERIMENT.out.join(ref_ch)

    // Evaluate each experiment against reference
    EVALUATE_EXPERIMENT(joined)

    // Collect all evaluation files and generate the final report
    EVALUATE_EXPERIMENT.out
        .map { exp, report -> report }
        .collect()
        .set { all_reports }

    GENERATE_REPORT(all_reports)
}
""")

main_nf_content = "".join(parts)

with open("/app/main.nf", "w") as f:
    f.write(main_nf_content)

print("Pipeline implementation written to /app/main.nf")
