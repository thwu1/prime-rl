FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY cases.json /app/cases.json
COPY problem_spec.txt /app/problem_spec.txt

RUN python3 -c "import json; d=json.load(open('/app/cases.json')); assert 'GC_BASE' in d and 'soil_layers' in d['GC_BASE'], 'cases.json validation failed'"
