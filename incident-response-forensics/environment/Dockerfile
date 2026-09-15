
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y python3 gcc libc6-dev && rm -rf /var/lib/apt/lists/*

COPY backdoor.c /tmp/backdoor.c
RUN gcc -O2 -s -o /tmp/backdoor /tmp/backdoor.c

COPY setup_evidence.py /tmp/setup_evidence.py
RUN python3 /tmp/setup_evidence.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
    python3-pip \
    tshark \
    yara \
    less \
    file \
    xxd \
    binutils \
    jq \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/evidence /app/evidence
COPY --from=builder /app/report /app/report

WORKDIR /app
