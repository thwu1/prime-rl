FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip libxml2-dev libxslt1-dev liburdfdom-tools && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY manipulator.xacro /app/manipulator.xacro

WORKDIR /app
