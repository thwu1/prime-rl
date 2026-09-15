FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install task environment dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        gcc \
        make \
        perl \
        wget \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set up application directory structure
RUN mkdir -p /app/src /app/profiles /app/analysis /app/hotfixes /app/FlameGraph

# Copy source code
COPY src/ /app/src/

# Copy profiling data
COPY profiles/ /app/profiles/

# Copy analysis artifacts (includes engineer's report and pre-generated diff)
COPY analysis/ /app/analysis/

# Copy hotfix patches
COPY hotfixes/ /app/hotfixes/

# Download Brendan Gregg's FlameGraph tools
RUN wget -q -O /app/FlameGraph/flamegraph.pl \
        https://raw.githubusercontent.com/brendangregg/FlameGraph/master/flamegraph.pl && \
    wget -q -O /app/FlameGraph/difffolded.pl \
        https://raw.githubusercontent.com/brendangregg/FlameGraph/master/difffolded.pl && \
    wget -q -O /app/FlameGraph/stackcollapse-perf.pl \
        https://raw.githubusercontent.com/brendangregg/FlameGraph/master/stackcollapse-perf.pl && \
    chmod +x /app/FlameGraph/*.pl

WORKDIR /app
