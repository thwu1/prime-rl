FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip jq && rm -rf /var/lib/apt/lists/*

RUN pip3 install lark==1.2.2 check-jsonschema==0.29.4

RUN mkdir -p /app/semantics /app/programs /app/schema

COPY app_setup/imp.lark /app/imp.lark
COPY app_setup/semantics/ /app/semantics/
COPY app_setup/programs/ /app/programs/
COPY app_setup/schema/ /app/schema/

WORKDIR /app
