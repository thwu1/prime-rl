
FROM python:3.12-slim AS generator
RUN pip install obspy==1.5.0
RUN mkdir -p /app
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    gfortran \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY --from=generator /app/observations.json /app/observations.json

WORKDIR /app
