FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    g++-14 \
    git \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Clone SDSL v3 headers (header-only library, no cmake build needed)
RUN git clone --depth 1 https://github.com/xxsds/sdsl-lite.git /opt/sdsl

# Verify SDSL headers compile and work correctly
COPY verify_sdsl.cpp /tmp/verify_sdsl.cpp
RUN g++-14 -std=c++17 -O2 -I/opt/sdsl/include -o /tmp/verify_sdsl /tmp/verify_sdsl.cpp -pthread && \
    /tmp/verify_sdsl && \
    rm -f /tmp/verify_sdsl /tmp/verify_sdsl.cpp

# Generate deterministic corpus and query patterns
COPY generate_corpus.py /tmp/generate_corpus.py
RUN python3 /tmp/generate_corpus.py && rm -f /tmp/generate_corpus.py

WORKDIR /app
