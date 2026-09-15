FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY arch_model.py /app/arch_model.py
COPY power_model.py /app/power_model.py
COPY constraints.yaml /app/constraints.yaml
COPY output_schema.json /app/output_schema.json
COPY setup_env.py /tmp/setup_env.py
RUN python3 /tmp/setup_env.py && rm /tmp/setup_env.py

WORKDIR /app
