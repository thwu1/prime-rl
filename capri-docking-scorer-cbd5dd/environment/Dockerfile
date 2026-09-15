FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    make \
    libeigen3-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY data /app/data
COPY capri_scorer.cpp /app/capri_scorer.cpp
COPY Makefile /app/Makefile

WORKDIR /app

