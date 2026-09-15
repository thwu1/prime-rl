FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS datagen
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==2.1.3 scipy==1.14.1 -q
RUN mkdir -p /app/data
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/models /app/results

COPY --from=datagen /app/data/observations.csv /app/data/observations.csv
COPY config.json /app/data/config.json
COPY model_a.py /app/models/model_a.py
COPY model_b.py /app/models/model_b.py
COPY model_c.py /app/models/model_c.py
COPY model_d.py /app/models/model_d.py

WORKDIR /app
