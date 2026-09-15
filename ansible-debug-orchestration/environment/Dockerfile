
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    cron \
    sudo \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install ansible-core==2.16.0 passlib==1.7.4

COPY project/ /app/

RUN mkdir -p /app/filter_plugins

RUN echo "batterystaple" > /tmp/vp.txt && \
    printf '%s\n' '---' 'db_password: "S3cur3P@ss!"' 'api_key: "ak-7f3d9a2b1c4e5f6789"' 'admin_email: "admin@example.com"' > /app/secrets.yml && \
    ansible-vault encrypt --vault-password-file /tmp/vp.txt /app/secrets.yml && \
    rm /tmp/vp.txt

WORKDIR /app
