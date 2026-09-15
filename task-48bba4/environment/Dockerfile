FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY circuit.qasm /app/circuit.qasm
COPY target_unitary.json /app/target_unitary.json
COPY hardware_specs.json /app/hardware_specs.json
COPY pipeline.py /app/pipeline.py
COPY validation_report.json /app/validation_report.json
