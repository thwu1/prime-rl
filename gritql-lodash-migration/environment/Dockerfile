FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install grit CLI from pinned GitHub release binary (auto-detect architecture)
RUN ARCH=$(uname -m) && \
    curl -fsSL -L \
    "https://github.com/biomejs/gritql/releases/download/v0.1.0-alpha.1743007075/grit-${ARCH}-unknown-linux-gnu.tar.gz" \
    -o /tmp/grit.tar.gz && \
    mkdir -p /tmp/grit-extract && \
    tar -xzf /tmp/grit.tar.gz -C /tmp/grit-extract && \
    find /tmp/grit-extract -name grit -type f -exec cp {} /usr/local/bin/grit \; && \
    chmod +x /usr/local/bin/grit && \
    rm -rf /tmp/grit.tar.gz /tmp/grit-extract && \
    grit --version

WORKDIR /app
RUN mkdir -p /app/.grit/patterns

COPY grit.yaml /app/.grit/grit.yaml
COPY lodash_to_native.md /app/.grit/patterns/lodash_to_native.md
