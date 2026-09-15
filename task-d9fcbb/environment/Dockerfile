
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://releases.hashicorp.com/terraform/1.9.0/terraform_1.9.0_linux_amd64.zip -o /tmp/terraform.zip \
    && unzip /tmp/terraform.zip -d /usr/local/bin/ \
    && rm /tmp/terraform.zip \
    && chmod +x /usr/local/bin/terraform \
    && terraform version

RUN mkdir -p /app/generated/network /app/generated/app /app/generated/monitoring
WORKDIR /app

COPY initial_main.tf /app/main.tf
RUN terraform init && terraform apply -auto-approve

RUN rm /app/main.tf

COPY architecture.md /app/ARCHITECTURE.md
COPY proposals/ /app/proposals/

WORKDIR /app
