FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu

WORKDIR /app

COPY config.py /app/config.py
COPY utils.py /app/utils.py
COPY skeleton.py /app/skeleton.py

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
