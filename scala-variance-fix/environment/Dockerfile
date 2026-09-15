FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y \
        openjdk-17-jdk-headless \
        python3-pip \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

RUN mkdir -p /app/src

COPY ["src/project.scala", "/app/src/project.scala"]
COPY ["src/core.scala", "/app/src/core.scala"]
COPY ["src/codec.scala", "/app/src/codec.scala"]
COPY ["src/typeclasses.scala", "/app/src/typeclasses.scala"]
COPY ["src/evidence.scala", "/app/src/evidence.scala"]
COPY ["src/containers.scala", "/app/src/containers.scala"]
COPY ["src/pipeline.scala", "/app/src/pipeline.scala"]
COPY ["src/Main.scala", "/app/src/Main.scala"]

WORKDIR /app

