FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    perl \
    git \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY workload.c /app/workload.c
COPY test_data.txt /app/test_data.txt
COPY index_data.txt /app/index_data.txt
COPY reference_output.txt /app/reference_output.txt
COPY profile_before.folded /app/profile_before.folded
COPY profile_after.folded /app/profile_after.folded
COPY config.ini /app/config.ini

RUN git clone --depth 1 https://github.com/brendangregg/FlameGraph.git /app/FlameGraph

WORKDIR /app
