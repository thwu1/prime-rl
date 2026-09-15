FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip proj-bin proj-data jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/model/active-crust/fault \
             /app/model/active-crust/grid \
             /app/docs /app/output

COPY calc-config.json /app/model/calc-config.json
COPY gmm-config.json /app/model/active-crust/gmm-config.json
COPY sources.xml /app/model/active-crust/fault/sources.xml
COPY utm-traces.csv /app/model/active-crust/fault/utm-traces.csv
COPY rates.csv /app/model/active-crust/grid/rates.csv
COPY docs/ /app/docs/

WORKDIR /app
