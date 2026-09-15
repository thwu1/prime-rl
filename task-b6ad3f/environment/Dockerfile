FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    jq \
    w3m \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/server_state /app/output /app/output_a /app/output_b /app/output_c /app/spec /app/validation

COPY data/server_state/ /app/data/server_state/
COPY data/transaction_bundle.json /app/data/transaction_bundle.json
COPY processor_a.py /app/processor_a.py
COPY processor_b.py /app/processor_b.py
COPY processor_c.py /app/processor_c.py
COPY spec/ /app/spec/

RUN python3 /app/processor_a.py \
    --bundle /app/data/transaction_bundle.json \
    --state-dir /app/data/server_state \
    --output-dir /app/output_a \
    --base-url http://fhir.example.org

RUN python3 /app/processor_b.py \
    --bundle /app/data/transaction_bundle.json \
    --state-dir /app/data/server_state \
    --output-dir /app/output_b \
    --base-url http://fhir.example.org

RUN python3 /app/processor_c.py \
    --bundle /app/data/transaction_bundle.json \
    --state-dir /app/data/server_state \
    --output-dir /app/output_c \
    --base-url http://fhir.example.org

WORKDIR /app
