FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Install task environment tools (DNS, HAProxy, Ansible for validation)
RUN apt-get update && apt-get install -y \
    bind9 \
    bind9-utils \
    bind9-dnsutils \
    haproxy \
    ansible \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Create runtime directories
RUN mkdir -p /run/haproxy

# Copy broken infrastructure configuration files
COPY app/ /app/

WORKDIR /app

