#!/bin/bash
set -e


# Copy solution evaluator to /app
cp /solution/evaluator.py /app/evaluate.py

# Create the pipeline entry point that the tests expect
printf '#!/bin/bash\nset -e\ncd /app\npython3 /app/evaluate.py\n' > /app/run_pipeline.sh
chmod +x /app/run_pipeline.sh

# Run the pipeline
cd /app
bash /app/run_pipeline.sh
