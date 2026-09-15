FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install docdeid==1.0.1

COPY pipeline.py /app/pipeline.py
COPY clinical_notes/ /app/clinical_notes/
COPY lookup_data/ /app/lookup_data/
COPY patients.json /app/patients.json

RUN mkdir -p /app/output

WORKDIR /app
