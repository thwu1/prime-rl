#!/usr/bin/env python3
"""
Fix all four bugs in the Nextflow scatter-gather pipeline.

Bug 1 (groupTuple wrong index): COMPUTE_STATS output has (sample_id, batch, file).
    groupTuple() defaults to by:0, grouping by sample_id instead of batch.
    Fix: reorder output to (batch, sample_id, file) so groupTuple() groups by batch.

Bug 2 (script interpolation): AGGREGATE_BATCH uses triple-single-quote script block
    where ${batch} is needed for Nextflow interpolation. In ''' blocks, ${batch} is
    treated as a bash variable (empty).
    Fix: switch to triple-double-quote and escape bash variables.

Bug 3 (collect flattens tuples): AGGREGATE_BATCH.out is a tuple channel (batch, file).
    collect() with default flat:true flattens to [batch1, file1, batch2, file2],
    mixing strings and files, which breaks path() staging.
    Fix: map to extract files first, then collect.

Bug 4 (errorStrategy hides failures): nextflow.config has errorStrategy='ignore'
    which silently swallows all process errors.
    Fix: remove errorStrategy='ignore'.
"""

import re

# --- Fix Bug 4: remove errorStrategy from nextflow.config ---
with open("/app/nextflow.config") as f:
    config = f.read()

config = re.sub(r"\s*errorStrategy\s*=\s*'ignore'\s*\n", "\n", config)

with open("/app/nextflow.config", "w") as f:
    f.write(config)

print("Fixed Bug 4: removed errorStrategy='ignore' from nextflow.config")

# --- Fix Bugs 1, 2, 3 in main.nf ---
with open("/app/main.nf") as f:
    main_nf = f.read()

# Bug 1: Reorder COMPUTE_STATS output to put batch first
main_nf = main_nf.replace(
    'tuple val(sample_id), val(batch), path("${sample_id}.stats")',
    'tuple val(batch), val(sample_id), path("${sample_id}.stats")',
    1  # only replace in the output section (first occurrence after input)
)

# We need to be more precise - only change the output declaration, not the input.
# The input has: tuple val(sample_id), val(batch), path(datafile)
# The output has: tuple val(sample_id), val(batch), path("${sample_id}.stats")
# After the replace above, only the output line (with the quoted path) was changed.

# Bug 2: Fix AGGREGATE_BATCH script from ''' to """ with escaped bash variables
old_agg_script = """    script:
    '''
    echo "batch,total_sum,total_count,num_samples" > ${batch}_summary.csv
    total_sum=0
    total_count=0
    num_samples=0
    for f in *.stats; do
        s=$(cut -d',' -f3 "$f")
        c=$(cut -d',' -f4 "$f")
        total_sum=$((total_sum + s))
        total_count=$((total_count + c))
        num_samples=$((num_samples + 1))
    done
    echo "${batch},${total_sum},${total_count},${num_samples}" >> ${batch}_summary.csv
    '''"""

new_agg_script = '''    script:
    """
    echo "batch,total_sum,total_count,num_samples" > ${batch}_summary.csv
    total_sum=0
    total_count=0
    num_samples=0
    for f in *.stats; do
        s=\\$(cut -d',' -f3 "\\$f")
        c=\\$(cut -d',' -f4 "\\$f")
        total_sum=\\$((total_sum + s))
        total_count=\\$((total_count + c))
        num_samples=\\$((num_samples + 1))
    done
    echo "${batch},\\${total_sum},\\${total_count},\\${num_samples}" >> ${batch}_summary.csv
    """'''

main_nf = main_nf.replace(old_agg_script, new_agg_script)

print("Fixed Bug 2: switched AGGREGATE_BATCH script to triple-double-quotes with escaping")

# Bug 3: Fix collect to extract only files before collecting
main_nf = main_nf.replace(
    """    AGGREGATE_BATCH.out
        .collect()
        .set { all_summaries }""",
    """    AGGREGATE_BATCH.out
        .map { batch, summary -> summary }
        .collect()
        .set { all_summaries }"""
)

print("Fixed Bug 3: added map to extract files before collect")
print("Fixed Bug 1: reordered COMPUTE_STATS output to (batch, sample_id, file)")

with open("/app/main.nf", "w") as f:
    f.write(main_nf)

print("All fixes applied to /app/main.nf and /app/nextflow.config")
