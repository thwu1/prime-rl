FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip jq && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pyyaml==6.0.2

RUN mkdir -p /app/templates /app/containers

COPY templates/postgres.template.yml /app/templates/
COPY templates/redis.template.yml /app/templates/
COPY templates/web.template.yml /app/templates/
COPY templates/web.ratelimited.template.yml /app/templates/
COPY templates/web.ssl.template.yml /app/templates/
COPY templates/web.letsencrypt.ssl.template.yml /app/templates/

COPY containers/app.yml /app/containers/
COPY containers/web_only.yml /app/containers/
COPY containers/data.yml /app/containers/

COPY resolve.py /app/
COPY launcher /app/
COPY deployment.json /app/

WORKDIR /app
