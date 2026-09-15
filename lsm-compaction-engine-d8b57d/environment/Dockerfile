FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y default-jdk python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY src/ /app/src/
COPY build.sh /app/build.sh
RUN chmod +x /app/build.sh

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
