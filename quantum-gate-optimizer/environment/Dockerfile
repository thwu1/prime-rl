FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /app/benchmarks /app/results

COPY gates.py /app/gates.py
COPY circuit.py /app/circuit.py
COPY optimizer_skeleton.py /app/optimizer.py
COPY qasm_io_skeleton.py /app/qasm_io.py
COPY run_pipeline_skeleton.py /app/run_pipeline.py
COPY Makefile /app/Makefile
COPY benchmarks/ /app/benchmarks/

WORKDIR /app
