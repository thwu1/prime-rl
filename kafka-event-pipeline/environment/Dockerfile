FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    openjdk-21-jdk-headless \
    python3-pip \
    python3-dev \
    sqlite3 \
    wget \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

ENV KAFKA_VERSION=3.7.0
ENV SCALA_VERSION=2.13
ENV KAFKA_HOME=/opt/kafka
ENV PATH="${KAFKA_HOME}/bin:${PATH}"

RUN wget -q "https://archive.apache.org/dist/kafka/${KAFKA_VERSION}/kafka_${SCALA_VERSION}-${KAFKA_VERSION}.tgz" -O /tmp/kafka.tgz && \
    tar -xzf /tmp/kafka.tgz -C /opt/ && \
    ln -s "/opt/kafka_${SCALA_VERSION}-${KAFKA_VERSION}" /opt/kafka && \
    rm /tmp/kafka.tgz

RUN mkdir -p /var/lib/kafka/data

COPY kraft-server.properties /opt/kafka/config/kraft/server.properties

RUN KAFKA_CLUSTER_ID=$(/opt/kafka/bin/kafka-storage.sh random-uuid) && \
    /opt/kafka/bin/kafka-storage.sh format -t "$KAFKA_CLUSTER_ID" -c /opt/kafka/config/kraft/server.properties

COPY start-kafka.sh /usr/local/bin/start-kafka.sh
RUN chmod +x /usr/local/bin/start-kafka.sh

RUN mkdir -p /app
COPY app/config.py /app/config.py
COPY app/models.py /app/models.py
COPY app/setup_topics.sh /app/setup_topics.sh
COPY app/processor.py /app/processor.py
COPY app/saga.py /app/saga.py
COPY app/outbox.py /app/outbox.py
RUN chmod +x /app/setup_topics.sh
WORKDIR /app
