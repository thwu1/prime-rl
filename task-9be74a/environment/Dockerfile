
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 scipy==1.14.1 pandas==2.2.3

COPY spx_implied_vol_20230215.csv /app/spx_implied_vol_20230215.csv
COPY rough_heston_lib/ /app/rough_heston_lib/

WORKDIR /app
