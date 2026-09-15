FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip sqlite3 jq make && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /opt/optframework /app

COPY optframework/framework.py /opt/optframework/framework.py
COPY optframework/problems.py /opt/optframework/problems.py
COPY optframework/run_test.py /opt/optframework/run_test.py

ENV PYTHONPATH=/opt/optframework

WORKDIR /app
