FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install stim==1.14.0

RUN mkdir -p /app/dems

COPY decoder_skeleton.py /app/decoder.py
COPY dems/chain.dem /app/dems/chain.dem
COPY dems/grid.dem /app/dems/grid.dem
COPY dems/boundary.dem /app/dems/boundary.dem
