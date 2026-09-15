FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/experiments/quadrature \
             /app/experiments/sparse_inverse \
             /app/experiments/stochastic \
             /app/logs

COPY calibration.json /app/calibration.json
COPY manifest.json /app/manifest.json
COPY schema.json /app/schema.json
COPY experiments/quadrature/integrand.py /app/experiments/quadrature/integrand.py
COPY experiments/quadrature/config.json /app/experiments/quadrature/config.json
COPY experiments/sparse_inverse/build_matrix.py /app/experiments/sparse_inverse/build_matrix.py
COPY experiments/sparse_inverse/targets.json /app/experiments/sparse_inverse/targets.json
COPY experiments/stochastic/setup.json /app/experiments/stochastic/setup.json
COPY logs/run_001.log /app/logs/run_001.log
COPY logs/run_002.log /app/logs/run_002.log

WORKDIR /app
