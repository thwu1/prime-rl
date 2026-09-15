FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY proof_structure.json /app/proof_structure.json
COPY engine_results.csv /app/engine_results.csv
COPY proof_mgr.py /app/proof_mgr.py
COPY validate_proof.sh /app/validate_proof.sh
RUN chmod +x /app/validate_proof.sh

WORKDIR /app
