FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    curl git python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY dotfiles/ /app/dotfiles/
COPY initial_shell_aliases /app/target/.shell_aliases
RUN mkdir -p /app/target/.config/.local_bin
COPY old_backup.sh /app/target/.config/.local_bin/old-backup.sh
RUN chmod +x /app/target/.config/.local_bin/old-backup.sh
COPY setup.sh /app/setup.sh
RUN chmod +x /app/setup.sh

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
