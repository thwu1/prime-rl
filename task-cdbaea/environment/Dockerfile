FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 h5py==3.12.1

RUN mkdir -p /app/data

COPY solver.py /app/solver.py
COPY evaluator.py /app/evaluator.py

WORKDIR /app
