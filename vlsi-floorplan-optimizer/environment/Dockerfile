FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

COPY generate_instances.py /tmp/generate_instances.py

RUN mkdir -p /app/instances && python3 /tmp/generate_instances.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip metis gnuplot-nox && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/instances /app/output

COPY --from=builder /app/instances/ /app/instances/
COPY evaluator.py /app/evaluator.py
COPY run_evaluation.py /app/run_evaluation.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
