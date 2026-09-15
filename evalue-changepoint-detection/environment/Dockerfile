
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1 -q

RUN mkdir -p /app/data /app/evalue

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY buggy_init.py /app/evalue/__init__.py
COPY buggy_martingales.py /app/evalue/martingales.py
COPY buggy_cusum.py /app/evalue/cusum.py
COPY buggy_confseq.py /app/evalue/confseq.py
COPY buggy_detect.py /app/detect.py

WORKDIR /app
