FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm -f /tmp/generate_data.py

COPY actuator_model_spec.md /app/actuator_model_spec.md

RUN mkdir -p /app/output

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
