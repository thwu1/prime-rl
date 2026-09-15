FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-apt \
    apache2 \
    openssh-server \
    fail2ban \
    iptables \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install ansible-core==2.16.3

COPY app/ /app/

WORKDIR /app
