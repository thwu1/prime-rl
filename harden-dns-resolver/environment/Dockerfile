FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && apt-get install -y python3 python3-pip tshark dnsutils && rm -rf /var/lib/apt/lists/*

COPY app/resolver.py /opt/task/resolver.py
COPY entrypoint.sh /opt/task/entrypoint.sh
RUN chmod +x /opt/task/entrypoint.sh

RUN mkdir -p /app && cp /opt/task/resolver.py /app/resolver.py

ENTRYPOINT ["/opt/task/entrypoint.sh"]
WORKDIR /app
