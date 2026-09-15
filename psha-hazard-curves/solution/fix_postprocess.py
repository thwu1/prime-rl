#!/usr/bin/env python3
"""
Fix all bugs in the post-processing pipeline.

Applies targeted corrections to the gnuplot script and the
postprocess.sh shell script that uses sqlite3 and jq.

"""


def fix_file(path, old, new):
    with open(path) as f:
        content = f.read()
    if old not in content:
        return False
    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)
    return True


# --- Gnuplot Bug 1: Missing terminal setting ---
# Without 'set terminal png', gnuplot uses the default terminal
# (often 'dumb' or 'unknown' in non-X11 environments), producing
# invalid output instead of a PNG image.
fix_file(
    "/app/pipeline/hazard_plot.gp",
    'set output "/app/output/hazard_curve.png"',
    'set terminal png size 800,600\nset output "/app/output/hazard_curve.png"',
)

# --- Gnuplot Bug 2: Wrong data separator ---
# The CSV file uses commas as delimiters, but the gnuplot script
# sets the separator to space. This causes gnuplot to treat each
# entire CSV line as a single field, failing to parse the data.
fix_file(
    "/app/pipeline/hazard_plot.gp",
    'set datafile separator " "',
    'set datafile separator ","',
)

# --- sqlite3 Bug: AVG instead of SUM for marginal distributions ---
# A marginal distribution sums contributions over the other dimensions.
# Using AVG divides by the number of distinct bins in those dimensions,
# producing values that do not sum to 1.0.
fix_file(
    "/app/pipeline/postprocess.sh",
    "AVG(contribution)",
    "SUM(contribution)",
)

# --- jq Bug 1: Wrong field name for site longitude ---
# The site.json uses "longitude" not "lon".
fix_file(
    "/app/pipeline/postprocess.sh",
    "$site.lon,",
    "$site.longitude,",
)

# --- jq Bug 2: Wrong field name for site latitude ---
# The site.json uses "latitude" not "lat".
fix_file(
    "/app/pipeline/postprocess.sh",
    "$site.lat,",
    "$site.latitude,",
)

# --- jq Bug 3: Wrong field name for return period ---
# The config.json uses "return_period_years" not "return_period".
fix_file(
    "/app/pipeline/postprocess.sh",
    "return_period_years: $config.disaggregation.return_period,",
    "return_period_years: $config.disaggregation.return_period_years,",
)

# --- jq Bug 4: Wrong field name for exposure ---
# The config.json uses "exposure_years" not "exposure".
fix_file(
    "/app/pipeline/postprocess.sh",
    "exposure_years: $config.exposure,",
    "exposure_years: $config.exposure_years,",
)

print("Post-processing fixes applied successfully.")
