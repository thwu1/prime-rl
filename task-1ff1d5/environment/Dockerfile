FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY raw_data/ /app/raw_data/
COPY sdtm_schema.json /app/sdtm_schema.json

RUN mkdir -p /app/sdtm_output

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 pyreadstat==1.2.7 pandas==2.2.3
