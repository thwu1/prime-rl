FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install adios2==2.10.1 numpy==2.1.3 -q

RUN mkdir -p /app/data
COPY generate_sensors.py /tmp/generate_sensors.py
RUN python3 /tmp/generate_sensors.py && rm /tmp/generate_sensors.py
COPY SPEC.md /app/SPEC.md

WORKDIR /app
