FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    cmake \
    gcc \
    make \
    gnuplot-nox \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/matrix_gen/src

COPY CMakeLists.txt /app/matrix_gen/CMakeLists.txt
COPY main.c /app/matrix_gen/src/main.c
COPY stencil.c /app/matrix_gen/src/stencil.c
COPY stencil.h /app/matrix_gen/src/stencil.h
COPY naive_solver.py /app/naive_solver.py
COPY benchmark_log.txt /app/benchmark_log.txt

WORKDIR /app
