
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    python3 \
    python3-pip \
    time \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

COPY problems/ /app/problems/
COPY submissions/ /app/submissions/
COPY testlib.h /app/testlib.h

WORKDIR /app
