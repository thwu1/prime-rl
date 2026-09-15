FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip jq && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

RUN mkdir -p /app/metadata/broker_configs /app/tools

COPY metadata/topic_descriptions.txt /app/metadata/topic_descriptions.txt
COPY metadata/log_dirs.json /app/metadata/log_dirs.json
COPY metadata/disk_quotas.csv /app/metadata/disk_quotas.csv
COPY metadata/constraints.yaml /app/metadata/constraints.yaml
COPY metadata/broker_configs/server-0.properties /app/metadata/broker_configs/server-0.properties
COPY metadata/broker_configs/server-1.properties /app/metadata/broker_configs/server-1.properties
COPY metadata/broker_configs/server-2.properties /app/metadata/broker_configs/server-2.properties
COPY metadata/broker_configs/server-3.properties /app/metadata/broker_configs/server-3.properties
COPY metadata/broker_configs/server-4.properties /app/metadata/broker_configs/server-4.properties
COPY metadata/broker_configs/server-5.properties /app/metadata/broker_configs/server-5.properties
COPY kafkactl /app/tools/kafkactl
RUN chmod +x /app/tools/kafkactl
RUN ln -s /app/tools/kafkactl /usr/local/bin/kafkactl

WORKDIR /app
