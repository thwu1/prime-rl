FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS build

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1 -q

COPY app_files/ /app/

RUN chmod +x /app/pipeline/extract.sh

RUN python3 /app/setup_env.py && rm /app/setup_env.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1 -q

COPY --from=build /app/ /app/

WORKDIR /app
