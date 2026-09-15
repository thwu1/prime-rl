FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    make \
    jq \
    graphviz \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/proof_engine /app/proofs

COPY models.py /app/proof_engine/models.py
COPY engine_stub.py /app/proof_engine/engine.py
COPY __init__.py /app/proof_engine/__init__.py
COPY test_integration.py /app/proof_engine/test_integration.py
COPY Makefile /app/Makefile
COPY validate_proof.py /app/validate_proof.py
COPY ag_arbiter.json /app/proofs/ag_arbiter.json
COPY ag_cyclic.json /app/proofs/ag_cyclic.json
COPY casesplit_modes.json /app/proofs/casesplit_modes.json
COPY partition_bus.json /app/proofs/partition_bus.json
COPY stopat_depth.json /app/proofs/stopat_depth.json
COPY helper_fsm.json /app/proofs/helper_fsm.json
COPY multi_arbiter.json /app/proofs/multi_arbiter.json

WORKDIR /app
