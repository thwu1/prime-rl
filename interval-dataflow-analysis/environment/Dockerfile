FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    openjdk-21-jdk \
    maven \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pom.xml pom.xml
COPY src/ src/
COPY inputs/ inputs/
