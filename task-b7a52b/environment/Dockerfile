FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

COPY create_rootfile.py /tmp/create_rootfile.py

RUN pip3 install uproot==5.4.1 numpy==2.1.3 -q && python3 /tmp/create_rootfile.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY --from=builder /app/observations.root /app/observations.root

COPY model_config.json /app/model_config.json

WORKDIR /app
