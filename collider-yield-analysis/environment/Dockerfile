
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    make \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir numpy==1.26.4 uproot==5.3.0 awkward==2.6.0 pyyaml==6.0.2

RUN mkdir -p /app/data /app/paper /app/pipeline /app/results /app/calibration /app/intermediate

COPY paper.md /app/paper/analysis.md
COPY extract.py /app/pipeline/extract.py
COPY analyze.py /app/pipeline/analyze.py
COPY Makefile /app/pipeline/Makefile
COPY background.json /app/data/background_yields.json
COPY template.yaml /app/results/results.yaml

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app
