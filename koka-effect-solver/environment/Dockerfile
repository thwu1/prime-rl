FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Build the effects oracle binary from C source, then remove source
COPY oracle.c /tmp/oracle.c
RUN mkdir -p /app/reference && \
    gcc -O2 -o /app/reference/effects_oracle /tmp/oracle.c && \
    rm /tmp/oracle.c

# Copy Koka reference source files and specification documents
COPY koka_reference/ /app/koka_reference/
COPY spec/ /app/spec/
