FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip jq && rm -rf /var/lib/apt/lists/*

# Task-specific tools: DuckDB for batch SQL computation
RUN pip3 install duckdb==1.1.0

# Create directory structure
RUN mkdir -p /app/pipeline /app/data /app/logs

# Copy pipeline package
COPY pipeline/__init__.py /app/pipeline/__init__.py
COPY pipeline/progress.py /app/pipeline/progress.py
COPY pipeline/operators.py /app/pipeline/operators.py
COPY pipeline/snapshot.py /app/pipeline/snapshot.py

# Copy engine and supporting files
COPY engine.py /app/engine.py
COPY generator.py /app/generator.py
COPY run.py /app/run.py
COPY config.yaml /app/config.yaml
COPY diagnostic.log /app/logs/diagnostic.log

# Generate test data
RUN cd /app && python3 generator.py random > /app/data/transactions.jsonl && \
    python3 generator.py simplified > /app/data/simplified.jsonl

WORKDIR /app
