FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip curl jq && \
    rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install flask==3.0.3

RUN mkdir -p /app/data

COPY server.py /app/server.py
COPY start.sh /app/start.sh
COPY conformance-report.xml /app/conformance-report.xml
COPY data/weather_stations.geojson /app/data/weather_stations.geojson
COPY data/seismic_events.geojson /app/data/seismic_events.geojson

RUN chmod +x /app/start.sh

WORKDIR /app
