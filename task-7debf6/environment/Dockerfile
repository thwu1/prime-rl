FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip graphviz && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/app

COPY files/target/ /app/target/
COPY files/tests/ /app/tests/
COPY files/mutants/ /app/mutants/
COPY files/tools/ /app/tools/
COPY files/spec.json /app/spec.json

WORKDIR /app

RUN python3 /app/tools/apply_mutations.py
