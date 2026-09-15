FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /app/reference

COPY setup_topology.py /tmp/setup_topology.py
RUN python3 /tmp/setup_topology.py && rm /tmp/setup_topology.py

COPY buggy_router.py /app/dv_router.py

COPY setup_reference.py /tmp/setup_reference.py
RUN python3 /tmp/setup_reference.py && rm /tmp/setup_reference.py

WORKDIR /app
