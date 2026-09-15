FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y openjdk-21-jre-headless wget python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app && \
    wget -nv http://nightly.tlapl.us/dist/tla2tools.jar -O /app/tla2tools.jar

COPY TCommit.tla /app/TCommit.tla
COPY TwoPhase.tla /app/TwoPhase.tla
COPY TwoPhase.cfg /app/TwoPhase.cfg

WORKDIR /app
