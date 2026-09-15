FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY data/nacl.cif /app/data/nacl.cif
COPY data/calcite.cif /app/data/calcite.cif
COPY data/batio3.cif /app/data/batio3.cif
COPY data/rutile.cif /app/data/rutile.cif
COPY data/cuo.cif /app/data/cuo.cif

WORKDIR /app
