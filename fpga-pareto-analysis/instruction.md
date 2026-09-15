The `/app/data/` directory contains the ResBench benchmark dataset — hardware synthesis results from multiple LLMs generating FPGA designs across various hardware module categories. The dataset files are undocumented; explore their structure to understand the schema.

An analysis specification at `/app/spec.yaml` defines the required outputs, parameters, and output formats. Produce all five output files described there in `/app/results/`.

The complete analysis pipeline must be executable via `python3 /app/analyze.py`.