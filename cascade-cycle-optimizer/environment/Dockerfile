FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/plants /app/commissioning

COPY plants/plant_a.json /app/plants/plant_a.json
COPY plants/plant_b.json /app/plants/plant_b.json
COPY plants/plant_c.json /app/plants/plant_c.json
COPY commissioning/plant_a_field.json /app/commissioning/plant_a_field.json

