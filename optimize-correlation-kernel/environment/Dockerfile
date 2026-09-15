FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    make \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY correlate.cpp /app/correlate.cpp
COPY Makefile /app/Makefile
COPY generate.py /app/generate.py

RUN python3 /app/generate.py

WORKDIR /app
