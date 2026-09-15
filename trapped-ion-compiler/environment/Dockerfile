FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip python3-dev && rm -rf /var/lib/apt/lists/*

RUN pip3 install bqskit==1.2.1

RUN mkdir -p /app

COPY input_circuit.qasm /app/input_circuit.qasm
COPY broken_gates.py /app/gates.py
COPY broken_model.py /app/model.py
COPY broken_pipeline.py /app/compile_pipeline.py

WORKDIR /app
