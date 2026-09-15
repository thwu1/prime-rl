FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip openssl && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /challenge /app

COPY curve_params.json /challenge/curve_params.json
COPY captures.json /challenge/captures.json
COPY challenge_message.txt /challenge/challenge_message.txt
COPY libecc_params.py /challenge/libecc_params.py
RUN chmod +x /challenge/libecc_params.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
