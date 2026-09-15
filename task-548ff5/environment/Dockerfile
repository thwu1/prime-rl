FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pycryptodome==3.21.0 -q

COPY setup_artifacts.py /tmp/setup_artifacts.py
RUN python3 /tmp/setup_artifacts.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    john \
    hashcat \
    python3-pip \
    jq \
    file \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/ /app/
WORKDIR /app
