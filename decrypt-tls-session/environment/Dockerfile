FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

COPY generate_forensics.py /tmp/generate_forensics.py

RUN pip3 install --no-cache-dir cryptography==43.0.0 && \
    python3 /tmp/generate_forensics.py

# --- Final stage: only the generated data, no generator script or deps ---
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/tls_forensics/captures /opt/tls_forensics/captures
COPY --from=builder /opt/tls_forensics/leaked_key_alpha.hex /opt/tls_forensics/leaked_key_alpha.hex
COPY --from=builder /opt/tls_forensics/leaked_key_beta.hex /opt/tls_forensics/leaked_key_beta.hex

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 cryptography==43.0.0
