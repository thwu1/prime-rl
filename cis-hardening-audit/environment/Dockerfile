FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    openssh-server \
    auditd \
    jq \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Create backup files and set deliberately insecure permissions
RUN touch /etc/passwd- /etc/shadow- /etc/group- /etc/gshadow- && \
    chmod 0666 /etc/shadow && \
    chmod 0666 /etc/gshadow && \
    chmod 0666 /etc/shadow- && \
    chmod 0666 /etc/gshadow- && \
    chmod 0666 /etc/passwd- && \
    chmod 0666 /etc/group-

# Create necessary directories
RUN mkdir -p /etc/audit/rules.d /etc/sysctl.d /etc/security /app

# Create SSH banner file
RUN echo "Authorized access only. All activity is monitored and logged." > /etc/issue.net

# Ensure opasswd file exists for audit rules
RUN touch /etc/security/opasswd

# Place the broken hardening script
COPY harden.sh /app/harden.sh
RUN chmod +x /app/harden.sh

