FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    gcc \
    make \
    liblapack-dev \
    libblas-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4

RUN mkdir -p /app/solver /app/csolver

COPY FORMULATION.md /app/FORMULATION.md
COPY data_gen.py /app/data_gen.py
COPY solver/__init__.py /app/solver/__init__.py
COPY solver/types.py /app/solver/types.py
COPY solver/minimal_solver.py /app/solver/minimal_solver.py
COPY solver/pose_recovery.py /app/solver/pose_recovery.py
COPY solver/robust_estimator.py /app/solver/robust_estimator.py
COPY csolver/eigensolve.h /app/csolver/eigensolve.h
COPY csolver/eigensolve.c /app/csolver/eigensolve.c
COPY csolver/Makefile /app/csolver/Makefile

WORKDIR /app
