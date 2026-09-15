FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY data/thermal_params.csv /app/data/thermal_params.csv
COPY data/sites.csv /app/data/sites.csv
COPY data/calibration_targets.csv /app/data/calibration_targets.csv
COPY data/model_spec.md /app/data/model_spec.md
COPY data/borehole_obs.tsv /app/data/borehole_obs.tsv
COPY data/site_borehole_map.csv /app/data/site_borehole_map.csv
COPY data/param_uncertainties.csv /app/data/param_uncertainties.csv

WORKDIR /app
