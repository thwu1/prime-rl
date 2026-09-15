FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq openssl && rm -rf /var/lib/apt/lists/*

COPY create_env.py /tmp/create_env.py
RUN python3 /tmp/create_env.py && rm /tmp/create_env.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
