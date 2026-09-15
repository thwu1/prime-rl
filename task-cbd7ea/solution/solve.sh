#!/bin/bash

# Step 1: Extract cache topology from hwloc XML using xmllint XPath queries.
# L1Cache (cache_type=1) is the data cache; L1iCache (cache_type=2) is instruction.
# string() returns the first match, which suffices since all per-core caches are identical.
L1D_SIZE=$(xmllint --xpath 'string(//object[@type="L1Cache"]/@cache_size)' /app/data/hwloc_topology.xml)
L2_SIZE=$(xmllint --xpath 'string(//object[@type="L2Cache"]/@cache_size)' /app/data/hwloc_topology.xml)
L3_SIZE=$(xmllint --xpath 'string(//object[@type="L3Cache"]/@cache_size)' /app/data/hwloc_topology.xml)

echo "Cache topology from hwloc XML: L1d=${L1D_SIZE}B L2=${L2_SIZE}B L3=${L3_SIZE}B"

# Step 2: Compute roofline model and generate gnuplot script
python3 /solution/solve.py --l1-size "$L1D_SIZE" --l2-size "$L2_SIZE" --l3-size "$L3_SIZE"

# Step 3: Generate roofline chart SVG using gnuplot
gnuplot /app/results/roofline.gp
echo "Roofline chart generated at /app/results/roofline_chart.svg"
