FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless \
    python3-pip \
    wget \
    netcat-openbsd \
    procps \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV KAFKA_HOME=/app/kafka
ENV PATH=$KAFKA_HOME/bin:$JAVA_HOME/bin:$PATH
ENV KAFKA_HEAP_OPTS="-Xmx512M -Xms256M"

RUN wget -q https://archive.apache.org/dist/kafka/3.6.1/kafka_2.13-3.6.1.tgz -O /tmp/kafka.tgz && \
    mkdir -p /app/kafka && \
    tar -xzf /tmp/kafka.tgz -C /app/kafka --strip-components=1 && \
    rm /tmp/kafka.tgz

RUN mkdir -p /app/configs /app/evaluation /app/verification

COPY server.properties.broken /app/kafka/config/kraft/server.properties
COPY workloads.md /app/workloads.md
COPY config_proposals.md /app/config_proposals.md

WORKDIR /app
