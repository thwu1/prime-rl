FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y jq python3-pip && rm -rf /var/lib/apt/lists/*

COPY ghenv.sh /app/ghenv.sh
COPY spec.txt /app/spec.txt
COPY testdata/ /app/testdata/

RUN chmod +x /app/ghenv.sh

WORKDIR /app
