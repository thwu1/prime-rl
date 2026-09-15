FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    jq \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install OPA binary for policy evaluation
RUN curl -L -o /usr/local/bin/opa https://openpolicyagent.org/downloads/v0.64.1/opa_linux_amd64_static \
    && chmod +x /usr/local/bin/opa \
    && opa version

# Copy task data into the container
COPY app/ /app/

# Create output directories the agent will write to
RUN mkdir -p /app/analysis /app/policies

WORKDIR /app
