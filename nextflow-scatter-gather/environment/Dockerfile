FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless \
        python3 \
        python3-pip \
        curl \
        gawk \
        procps && \
    rm -rf /var/lib/apt/lists/*

# Install Nextflow
ENV NXF_HOME=/root/.nextflow
RUN curl -s https://get.nextflow.io | bash && \
    mv nextflow /usr/local/bin/ && \
    chmod +x /usr/local/bin/nextflow && \
    nextflow info

# Copy pipeline project files
COPY app/ /app/

WORKDIR /app
