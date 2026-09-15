
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install pycryptodome==3.21.0 tinyec==0.4.0 dissononce==0.34.3

COPY vaultsync.py /app/vaultsync.py
COPY verify.py /app/verify.py

WORKDIR /app
