FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install Java (required by Nextflow) and utilities
RUN apt-get update && apt-get install -y \
    openjdk-17-jre-headless \
    curl \
    python3-pip \
    gawk \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Nextflow all-in-one distribution (all deps bundled, no capsule download)
ENV NXF_HOME=/root/.nextflow
RUN curl -fsSL -o /usr/local/bin/nextflow \
    https://github.com/nextflow-io/nextflow/releases/download/v23.10.1/nextflow-23.10.1-all && \
    chmod +x /usr/local/bin/nextflow && \
    nextflow -version

# Copy pipeline files to /app/
COPY pipeline/ /app/

WORKDIR /app
