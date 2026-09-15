FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3-pip \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /app/data

COPY pipeline.c /app/pipeline.c
COPY compute.h /app/compute.h
COPY Makefile /app/Makefile
COPY generate_input.py /tmp/generate_input.py
RUN python3 /tmp/generate_input.py > /app/data/numbers.txt && rm /tmp/generate_input.py
RUN make -C /app
