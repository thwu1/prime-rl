FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    openjdk-17-jre-headless \
    xxd \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://archive.apache.org/dist/kafka/3.7.1/kafka_2.13-3.7.1.tgz -O /tmp/kafka.tgz \
    && tar -xzf /tmp/kafka.tgz -C /opt/ \
    && mv /opt/kafka_2.13-3.7.1 /opt/kafka \
    && rm /tmp/kafka.tgz

ENV KAFKA_HOME=/opt/kafka
ENV PATH="${KAFKA_HOME}/bin:${PATH}"

RUN mkdir -p /app/kafka-data

COPY setup_data.py /tmp/setup_data.py
COPY format_reference.txt /app/kafka-data/format_reference.txt

RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

WORKDIR /app
