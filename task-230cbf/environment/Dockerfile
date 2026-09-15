FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    gnuplot-nox \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/plots

COPY data/experiment.csv /app/data/experiment.csv
COPY data/grid_spec.csv /app/data/grid_spec.csv
COPY data/submission_fun3d_sa.dat /app/data/submission_fun3d_sa.dat
COPY data/submission_overflow_sst.csv /app/data/submission_overflow_sst.csv
COPY data/submission_su2_sa.fwf /app/data/submission_su2_sa.fwf
COPY data/submission_tau_rsm.jsonl /app/data/submission_tau_rsm.jsonl
COPY data/submission_cfl3d_sa.tsv /app/data/submission_cfl3d_sa.tsv

RUN chmod -R a+r /app/data

WORKDIR /app
