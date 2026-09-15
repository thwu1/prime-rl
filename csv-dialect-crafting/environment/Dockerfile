FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-dev build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install clevercsv==0.8.5 chardet==5.2.0 regex==2024.11.6

RUN mkdir -p /app/challenges

WORKDIR /app
