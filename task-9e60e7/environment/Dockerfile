FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip curl && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data && \
    curl -sL --max-time 180 --retry 3 -o /app/data/dimuon.csv \
      "https://opendata.cern.ch/record/700/files/MuRun2010B.csv" && \
    test -s /app/data/dimuon.csv && \
    head -1 /app/data/dimuon.csv | grep -q "Run" && \
    wc -l /app/data/dimuon.csv | grep -q "100001"

WORKDIR /app
