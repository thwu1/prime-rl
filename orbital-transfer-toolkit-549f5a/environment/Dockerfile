FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 make && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/mission_data

COPY mission_data/scenario.toml /app/mission_data/scenario.toml
COPY mission_data/target_ephemeris.oem /app/mission_data/target_ephemeris.oem
COPY mission_data/tracking_data.dat /app/mission_data/tracking_data.dat

WORKDIR /app
