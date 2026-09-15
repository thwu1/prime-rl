
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Install system packages needed for the task environment
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        curl \
        jq \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Restate server and CLI binaries (linux x86_64)
RUN curl -L -o /tmp/restate-server.tar.xz \
        "https://restate.gateway.scarf.sh/latest/restate-server-x86_64-unknown-linux-musl.tar.xz" && \
    tar -xf /tmp/restate-server.tar.xz --strip-components=1 -C /usr/local/bin && \
    rm /tmp/restate-server.tar.xz && \
    curl -L -o /tmp/restate-cli.tar.xz \
        "https://restate.gateway.scarf.sh/latest/restate-cli-x86_64-unknown-linux-musl.tar.xz" && \
    tar -xf /tmp/restate-cli.tar.xz --strip-components=1 -C /usr/local/bin && \
    rm /tmp/restate-cli.tar.xz && \
    chmod +x /usr/local/bin/restate-server /usr/local/bin/restate

# Install Python SDK and ASGI server for the service
RUN pip3 install restate-sdk==0.18.1 hypercorn==0.18.0

# Copy the service into the task working directory
COPY service.py /app/service.py

WORKDIR /app
