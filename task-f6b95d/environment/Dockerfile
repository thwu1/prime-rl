FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install crosshair-tool==0.0.106

RUN mkdir -p /task_setup /app

COPY app/ /task_setup/

RUN cp -a /task_setup/. /app/

WORKDIR /app
