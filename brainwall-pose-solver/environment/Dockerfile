FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip build-essential jq xxd xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/include /app/src /app/tools /app/simulator

COPY spec.md /app/spec.md
COPY Makefile /app/Makefile
COPY nmms.h /app/include/nmms.h

COPY gen_cases.py /tmp/gen_cases.py
RUN python3 /tmp/gen_cases.py \
    && cd /app && tar cJf testdata.tar.xz cases/ \
    && rm -rf /app/cases /tmp/gen_cases.py

WORKDIR /app
