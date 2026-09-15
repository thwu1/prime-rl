FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip gcc build-essential && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/lib /app/testdata

COPY config.json /app/config.json
COPY setup_testdata.py /tmp/setup_testdata.py
RUN python3 /tmp/setup_testdata.py && rm /tmp/setup_testdata.py

WORKDIR /app
