FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/docs /app/tools

COPY benchmarks.fpcore /app/benchmarks.fpcore
COPY fpcore_syntax.txt /app/docs/fpcore_syntax.txt
COPY profiler.py /app/tools/profiler.py

WORKDIR /app
