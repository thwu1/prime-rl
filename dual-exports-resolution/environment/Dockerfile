FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y nodejs npm python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY lib/ /app/lib/
COPY consumer/ /app/consumer/

RUN chmod -R a+rX /app/lib/ /app/consumer/

RUN mkdir -p /app/node_modules/@mathkit && \
    ln -s /app/lib /app/node_modules/@mathkit/linalg

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
