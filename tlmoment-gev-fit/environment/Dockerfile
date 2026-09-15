FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data

COPY station_A.csv /data/station_A.csv
COPY station_B.csv /data/station_B.csv
COPY station_C.csv /data/station_C.csv
COPY station_D.csv /data/station_D.csv
COPY station_E.csv /data/station_E.csv

RUN test -f /data/station_A.csv && test -f /data/station_E.csv && echo "Data files verified"

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==2.1.3
