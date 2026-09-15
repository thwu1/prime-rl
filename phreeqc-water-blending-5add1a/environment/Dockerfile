FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    cmake \
    g++ \
    make \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app

COPY sources.json /app/sources.json
COPY scenarios.json /app/scenarios.json
