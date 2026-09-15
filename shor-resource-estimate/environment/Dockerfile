FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip python3-dev build-essential && rm -rf /var/lib/apt/lists/*

RUN pip3 install qualtran==0.7.0

WORKDIR /app

COPY targets.json /app/targets.json
COPY skeleton.py /app/analyze.py
