FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    libeccodes-tools \
    libeccodes-data \
    libeccodes-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install eccodes==1.7.1 numpy==1.26.4

COPY create_data.py /tmp/create_data.py
RUN python3 /tmp/create_data.py && rm /tmp/create_data.py

RUN mkdir -p /app/output/corrected

WORKDIR /app
