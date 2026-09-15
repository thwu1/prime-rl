#!/bin/bash

# Copy the pipeline script to /app
cp /solution/audit_pipeline.py /app/audit_pipeline.py

# Create the entry-point wrapper
printf '#!/bin/bash\npython3 /app/audit_pipeline.py /app/ecosystem\n' > /app/audit-pipeline.sh
chmod +x /app/audit-pipeline.sh

# Run the pipeline
bash /app/audit-pipeline.sh
