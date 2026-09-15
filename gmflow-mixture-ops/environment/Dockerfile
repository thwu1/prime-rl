FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PYTHONDONTWRITEBYTECODE=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

# PyTorch CPU-only — required by the GM operations library
RUN pip3 install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu

COPY app/ /app/
WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 scipy==1.14.1 numpy==2.1.3
