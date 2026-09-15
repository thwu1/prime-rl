FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/app

COPY sparse_matrix.py /app/sparse_matrix.py
COPY cg_solver.py /app/cg_solver.py
COPY preconditioner.py /app/preconditioner.py
COPY fmm_solver.py /app/fmm_solver.py
COPY poisson.py /app/poisson.py

WORKDIR /app
