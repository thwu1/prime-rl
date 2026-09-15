FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    proj-bin \
    proj-data \
    python3-pip \
    python3 \
    && rm -rf /var/lib/apt/lists/*

COPY survey_data.csv /app/survey_data.csv
COPY output_spec.json /app/output_spec.json

WORKDIR /app
