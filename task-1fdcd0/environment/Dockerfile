FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS data-gen
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==2.1.3 -q
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip gnuplot-nox && rm -rf /var/lib/apt/lists/*

COPY --from=data-gen /app/data/ /app/data/

RUN mkdir -p /app/output

WORKDIR /app
