FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    proj-bin \
    proj-data \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY scenarios.json /app/scenarios.json
COPY survey_observations.csv /app/survey_observations.csv
