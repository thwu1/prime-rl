
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y gcc binutils make python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY app/ /app/

# Preserve the original vulnerable source as a reference copy.
# The agent's task is to fix /app/src/secure_ops.c; this reference
# copy allows rebuilding the original vulnerable binary for comparison.
RUN mkdir -p /app/reference && \
    cp /app/src/secure_ops.c /app/reference/secure_ops_vulnerable.c

WORKDIR /app
