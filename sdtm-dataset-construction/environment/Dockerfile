FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/raw_data

COPY raw_data/patients.csv /app/raw_data/patients.csv
COPY raw_data/adverse_events.csv /app/raw_data/adverse_events.csv
COPY raw_data/vital_signs.csv /app/raw_data/vital_signs.csv
COPY raw_data/lab_results.csv /app/raw_data/lab_results.csv
COPY raw_data/drug_exposure.csv /app/raw_data/drug_exposure.csv
COPY raw_data/disposition.csv /app/raw_data/disposition.csv
COPY raw_data/protocol_info.json /app/raw_data/protocol_info.json

WORKDIR /app
