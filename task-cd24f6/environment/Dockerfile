FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip jq && rm -rf /var/lib/apt/lists/*

COPY spec.md /app/spec.md
COPY evaluate.py /app/evaluate.py
COPY benchmarks/ /app/benchmarks/

RUN printf '#!/usr/bin/env python3\nimport sys\nprint("Not implemented")\nsys.exit(1)\n' > /app/scheduler.py && chmod +x /app/scheduler.py

WORKDIR /app
