FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder


ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y gcc python3 && rm -rf /var/lib/apt/lists/*

COPY implant.c /tmp/implant.c
COPY gen_challenge.py /tmp/gen_challenge.py

RUN gcc -O2 -o /app/sample_alpha /tmp/implant.c && strip /app/sample_alpha

RUN sed -e 's/cdn-telemetry\.example\.com/cdn-analytics.example.net/g' \
    -e 's/api-metrics\.example\.com/api-health.example.net/g' \
    -e 's/netmond v2\.1\.4/netmond v3.0.1/g' \
    -e 's/agent-session-2024-rev3/agent-session-2025-rev1/g' \
    -e 's/monitor\.internal\.net/syslog.internal.net/g' \
    /tmp/implant.c > /tmp/implant_variant.c && \
    gcc -O2 -o /app/sample_beta /tmp/implant_variant.c && strip /app/sample_beta

RUN python3 /tmp/gen_challenge.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN echo 'wireshark-common wireshark-common/install-setuid boolean false' | debconf-set-selections && \
    apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    radare2 \
    tshark \
    gdb \
    binutils \
    xxd \
    yara \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/ /app/

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
