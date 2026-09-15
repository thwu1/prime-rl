FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/models/eight_schools /app/models/gp_regr /app/models/sir /app/results

COPY models/eight_schools/data.json /app/models/eight_schools/data.json
COPY models/eight_schools/model.stan /app/models/eight_schools/model.stan
COPY models/gp_regr/data.json /app/models/gp_regr/data.json
COPY models/gp_regr/model.stan /app/models/gp_regr/model.stan
COPY models/sir/data.json /app/models/sir/data.json
COPY models/sir/model.stan /app/models/sir/model.stan

WORKDIR /app
