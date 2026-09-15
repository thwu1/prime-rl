FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /opt/task_instance

COPY data/facilities.csv /opt/task_instance/facilities.csv
COPY data/shipping_costs.csv /opt/task_instance/shipping_costs.csv
COPY data/demand_scenarios.csv /opt/task_instance/demand_scenarios.csv
COPY data/parameters.json /opt/task_instance/parameters.json

RUN cp /opt/task_instance/* /app/data/

WORKDIR /app
