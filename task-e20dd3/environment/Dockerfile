FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && apt-get install -y python3-pip tshark && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY fingerprints.db /app/fingerprints.db
COPY spec.md /app/SPEC.md
COPY generate_capture.py /tmp/generate_capture.py
RUN python3 /tmp/generate_capture.py && rm /tmp/generate_capture.py

WORKDIR /app
