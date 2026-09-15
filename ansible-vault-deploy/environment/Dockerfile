FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    sudo \
    sshpass \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install ansible-core==2.16.3

# Ensure UIDs/GIDs needed by the task are free (clear any conflicts from base image)
RUN for uid in 5001 5002; do \
      u=$(getent passwd "$uid" 2>/dev/null | cut -d: -f1); \
      [ -n "$u" ] && userdel -f "$u" || true; \
    done && \
    g=$(getent group 5000 2>/dev/null | cut -d: -f1); \
    [ -n "$g" ] && groupdel "$g" || true

RUN mkdir -p /app/ansible-project/inventory \
    /app/ansible-project/group_vars \
    /app/ansible-project/host_vars \
    /app/ansible-project/roles \
    /app/ansible-project/templates \
    /app/ansible-project/vars

COPY broken_ansible.cfg /app/ansible-project/ansible.cfg
COPY broken_inventory /app/ansible-project/inventory/hosts
COPY group_vars_all.yml /app/ansible-project/group_vars/all.yml
COPY group_vars_webservers.yml /app/ansible-project/group_vars/webservers.yml
COPY group_vars_databases.yml /app/ansible-project/group_vars/databases.yml
COPY group_vars_monitoring.yml /app/ansible-project/group_vars/monitoring.yml
COPY host_vars_app1.yml /app/ansible-project/host_vars/app1.yml
COPY broken_template.j2 /app/ansible-project/templates/app_config.conf.j2
COPY project_requirements.md /app/ansible-project/REQUIREMENTS.md

WORKDIR /app/ansible-project
