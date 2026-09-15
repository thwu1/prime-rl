
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    perl \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Brendan Gregg's FlameGraph toolchain using curl (more reliable than git clone)
RUN mkdir -p /opt/FlameGraph && \
    curl -sSfL https://github.com/brendangregg/FlameGraph/archive/refs/heads/master.tar.gz | \
    tar xz -C /opt/FlameGraph --strip-components=1 && \
    chmod +x /opt/FlameGraph/*.pl

RUN mkdir -p /app/traces /app/output

# Generate trace data deterministically
COPY generate_traces.py /tmp/generate_traces.py
RUN python3 /tmp/generate_traces.py && rm /tmp/generate_traces.py

WORKDIR /app
