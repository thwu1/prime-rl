#!/usr/bin/env bash

# Copy implementations into place
cp /solution/engine_impl.py /app/qcsim/engine.py
cp /solution/diff_impl.py /app/qcsim/differentiation.py
cp /solution/qasm_parser_impl.py /app/qcsim/qasm_parser.py
cp /solution/pipeline_impl.sh /app/pipeline.sh
chmod +x /app/pipeline.sh

# Run the pipeline to generate results.db and report.json
bash /app/pipeline.sh
