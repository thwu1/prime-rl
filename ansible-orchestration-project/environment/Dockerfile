FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y \
    python3-pip \
    ansible-core \
    nginx \
    sudo \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install passlib==1.7.4

RUN mkdir -p /app

COPY fleet_inventory.json /app/fleet_inventory.json
COPY compliance_policies.yml /app/compliance_policies.yml
COPY create_vault.sh /tmp/create_vault.sh
RUN chmod +x /tmp/create_vault.sh && /tmp/create_vault.sh && rm /tmp/create_vault.sh

COPY fleet_spec.md /app/fleet_spec.md
COPY setup_broken_project.sh /tmp/setup_broken_project.sh
RUN chmod +x /tmp/setup_broken_project.sh && /tmp/setup_broken_project.sh && rm /tmp/setup_broken_project.sh

WORKDIR /app
