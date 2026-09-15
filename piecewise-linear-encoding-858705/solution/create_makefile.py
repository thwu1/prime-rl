#!/usr/bin/env python3
"""Create /app/Makefile with correct tab-indented recipes."""

MAKEFILE_CONTENT = """\
.PHONY: encode batch report sweep clean

encode:
\tpython3 /app/ple_encode.py --input $(INPUT) --n-bins $(NBINS) --format $(FORMAT) --output $(OUTPUT)

batch:
\t@mkdir -p $(OUTDIR)
\tpython3 /app/ple_encode.py --input $(INPUT) --n-bins $(NBINS) --format structured --output $(OUTDIR)/structured.npy
\tpython3 /app/ple_encode.py --input $(INPUT) --n-bins $(NBINS) --format flat --output $(OUTDIR)/flat.npy

report: batch
\tpython3 /app/gen_report.py $(OUTDIR)/structured.npy $(OUTDIR)/flat.npy $(NBINS) $(OUTDIR)/report.json

sweep:
\t@for N in 4 8 16 32 64; do \\
\t\tmkdir -p $(OUTDIR)/bins_$$N; \\
\t\tpython3 /app/ple_encode.py --input $(INPUT) --n-bins $$N --format structured --output $(OUTDIR)/bins_$$N/structured.npy; \\
\t\tpython3 /app/ple_encode.py --input $(INPUT) --n-bins $$N --format flat --output $(OUTDIR)/bins_$$N/flat.npy; \\
\tdone
\tpython3 /app/gen_sweep.py $(OUTDIR) $(OUTDIR)/sweep.json

clean:
\trm -f $(OUTDIR)/*.npy $(OUTDIR)/*.json
\trm -rf $(OUTDIR)/bins_*/
"""

with open('/app/Makefile', 'w') as f:
    f.write(MAKEFILE_CONTENT)
