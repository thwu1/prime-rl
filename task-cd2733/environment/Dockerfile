# Build stage: generate challenge data (secrets stay in this stage only)
FROM python:3.12-slim AS builder
RUN pip install pycryptodome==3.20.0
COPY setup.py /tmp/setup.py
RUN python3 /tmp/setup.py

# Final stage: clean runtime image
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    openssl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/pubkey.der /app/pubkey.der
COPY --from=builder /app/audit.db /app/audit.db
COPY --from=builder /app/intercepted.enc /app/intercepted.enc
COPY prng.py /app/prng.py
COPY keygen_template.py /app/keygen.py
COPY remediation_proposal.txt /app/remediation_proposal.txt

WORKDIR /app
