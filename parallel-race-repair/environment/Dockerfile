FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y gcc g++ clang libomp-dev make python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY src/ /app/src/
COPY Makefile /app/Makefile
COPY tsan.supp /app/tsan.supp
COPY candidates.md /app/candidates.md

WORKDIR /app
