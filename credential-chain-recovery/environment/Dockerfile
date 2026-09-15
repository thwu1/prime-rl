# Stage 1: build artifacts (this stage is discarded in the final image)
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3 \
    sqlite3 \
    gnupg \
    zip \
    openssl \
    && rm -rf /var/lib/apt/lists/*
COPY setup_artifacts.py /tmp/setup_artifacts.py
RUN python3 /tmp/setup_artifacts.py && rm /tmp/setup_artifacts.py

# Stage 2: final task image (no setup script, no build-time secrets)
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    gnupg \
    unzip \
    tcpdump \
    file \
    openssl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/incident /app/incident
WORKDIR /app
