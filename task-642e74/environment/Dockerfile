FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip jq sqlite3 xmlstarlet && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/measure /app/patients

COPY measure/ /app/measure/
COPY patients/ /app/patients/
COPY measure-parameters.xml /app/measure-parameters.xml

COPY init_terminology.sql /tmp/init_terminology.sql
RUN sqlite3 /app/terminology.db < /tmp/init_terminology.sql && rm /tmp/init_terminology.sql

WORKDIR /app
