FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/tools

COPY conntrack.py /app/conntrack.py
COPY datapath.py /app/datapath.py
COPY identity.py /app/identity.py
COPY policy.py /app/policy.py
COPY loadbalancer.py /app/loadbalancer.py
COPY config.json /app/config.json
COPY tools_init.py /app/tools/__init__.py
COPY tools_diagnose.py /app/tools/diagnose.py

WORKDIR /app
