FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    make \
    curl \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


COPY stream_analyzer.cpp /app/stream_analyzer.cpp
COPY Makefile /app/Makefile
COPY setup_simdjson.sh /app/setup_simdjson.sh

RUN chmod +x /app/setup_simdjson.sh

WORKDIR /app
