
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gnuplot-nox \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/cases /app/data /app/plots

COPY cases/case_a.fds /app/cases/case_a.fds
COPY cases/case_b.fds /app/cases/case_b.fds
COPY cases/case_c.fds /app/cases/case_c.fds
COPY cases/case_d.fds /app/cases/case_d.fds

COPY data/case_a_devc.csv /app/data/case_a_devc.csv
COPY data/case_b_devc.csv /app/data/case_b_devc.csv
COPY data/case_c_devc.csv /app/data/case_c_devc.csv
COPY data/case_d_devc.csv /app/data/case_d_devc.csv

COPY config.json /app/config.json

WORKDIR /app
