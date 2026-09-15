FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    gnuplot-nox \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY coolprop_co2.json /app/coolprop_co2.json
COPY cycle_params.json /app/cycle_params.json
COPY nist_co2_saturation.csv /app/nist_co2_saturation.csv
COPY nist_co2_350K.csv /app/nist_co2_350K.csv
COPY nist_co2_8MPa.tsv /app/nist_co2_8MPa.tsv

