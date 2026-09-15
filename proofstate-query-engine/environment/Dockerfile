FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip jq && \
    rm -rf /var/lib/apt/lists/*

COPY data/ /app/data/
COPY SPEC.md /app/SPEC.md

RUN python3 -c "import json, os; [json.load(open(os.path.join('/app/data', f))) for f in os.listdir('/app/data') if f.endswith('.json')]"

WORKDIR /app
