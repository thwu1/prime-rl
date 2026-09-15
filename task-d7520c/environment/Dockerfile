FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu
RUN pip3 install scipy==1.14.1 numpy==2.1.3

RUN mkdir -p /app/nf4_quant

COPY config.json /app/config.json
COPY init.py /app/nf4_quant/__init__.py
COPY quantization.py /app/nf4_quant/quantization.py
COPY memory.py /app/nf4_quant/memory.py

WORKDIR /app
