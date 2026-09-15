FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y build-essential python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src

COPY src/sdf.h /app/src/sdf.h
COPY src/sdf_prims.c /app/src/sdf_prims.c
COPY src/sdf_ops.c /app/src/sdf_ops.c
COPY Makefile /app/Makefile
COPY bindings.py /app/bindings.py
COPY scene.py /app/scene.py
COPY main.py /app/main.py
COPY eval_points.csv /app/eval_points.csv
COPY reference_samples.csv /app/reference_samples.csv

WORKDIR /app

