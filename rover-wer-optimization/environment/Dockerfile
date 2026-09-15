
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    make \
    git \
    perl \
    python3 \
    python3-pip \
    gawk \
    && rm -rf /var/lib/apt/lists/*

# Build SCTK from source
# rfilter1 may fail on newer libc but sclite/rover/sc_stats build fine
RUN git clone https://github.com/usnistgov/SCTK.git /opt/sctk && \
    cd /opt/sctk && \
    make config && \
    make all 2>&1 || echo "partial build failure (expected for rfilter1)" && \
    make install 2>&1 || echo "partial install failure" && \
    test -f /opt/sctk/bin/sclite && \
    test -f /opt/sctk/bin/rover && \
    test -f /opt/sctk/bin/sc_stats && \
    cp /opt/sctk/bin/sclite /usr/local/bin/ && \
    cp /opt/sctk/bin/rover /usr/local/bin/ && \
    cp /opt/sctk/bin/sc_stats /usr/local/bin/ && \
    rm -rf /opt/sctk/src

# Generate evaluation data with varied confidence profiles
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

RUN mkdir -p /app/results /app/work
WORKDIR /app
