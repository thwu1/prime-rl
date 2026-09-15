FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install stim==1.14.0 pymatching==2.2.1 numpy==1.26.4 scipy==1.14.1

RUN mkdir -p /app/circuits
WORKDIR /app

COPY generate_circuits.py /tmp/generate_circuits.py
RUN python3 /tmp/generate_circuits.py && rm /tmp/generate_circuits.py

COPY draft_analysis.py /app/draft_analysis.py
