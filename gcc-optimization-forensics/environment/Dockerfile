
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/cases /app/fixed

COPY cases/case1.c /app/cases/case1.c
COPY cases/case2.c /app/cases/case2.c
COPY cases/case3.c /app/cases/case3.c
COPY cases/case4.c /app/cases/case4.c
COPY cases/case5.c /app/cases/case5.c

WORKDIR /app
