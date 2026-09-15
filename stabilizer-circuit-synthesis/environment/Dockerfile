
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install stim==1.15.0

COPY codes_db.json /app/codes_db.json
COPY tools/ /app/tools/

RUN mkdir -p /app/output

WORKDIR /app
