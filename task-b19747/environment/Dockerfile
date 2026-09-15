FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results

COPY app/models.md /app/models.md
COPY app/data/eight_schools.json /app/data/eight_schools.json
COPY app/data/gp_regr.json /app/data/gp_regr.json
COPY app/data/sir.json /app/data/sir.json

WORKDIR /app
