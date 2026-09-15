FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip glpk-utils && \
    rm -rf /var/lib/apt/lists/*

COPY gen_instances.py /tmp/gen_instances.py
RUN python3 /tmp/gen_instances.py && rm /tmp/gen_instances.py

COPY depot_selection_template.mod /app/models/depot_selection_template.mod

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
