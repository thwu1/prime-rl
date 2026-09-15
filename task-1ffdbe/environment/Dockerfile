FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1 -q

COPY app/ /app/

RUN mkdir -p /app/reference && python3 /app/reference/generate_ref.py && rm /app/reference/generate_ref.py

WORKDIR /app
