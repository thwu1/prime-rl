
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip python3-dev build-essential && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1 stim==1.14.0 ldpc==2.2.0 -q

COPY qec_decoder.py /app/qec_decoder.py
COPY dem_files/ /app/dem_files/
