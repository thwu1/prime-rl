FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-numpy \
    python3-scipy \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY brusselator_problem.py /app/brusselator_problem.py

WORKDIR /app
