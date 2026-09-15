FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    openssh-server \
    libpam-pwquality \
    kmod \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/.baseline /etc/ssh/sshd_config.d

# Remove 99-sysctl.conf symlink so sysctl.conf is not re-loaded via sysctl.d
RUN rm -f /etc/sysctl.d/99-sysctl.conf

# Set up insecure sysctl drop-in configurations (two conflicting files)
COPY 99-insecure.conf /etc/sysctl.d/99-insecure.conf
COPY 50-network.conf /etc/sysctl.d/50-network.conf

# Set up insecure SSH configuration with Include directive and Match block
COPY sshd_config /etc/ssh/sshd_config
COPY 90-override.conf /etc/ssh/sshd_config.d/90-override.conf

# Set insecure password policies in login.defs
RUN sed -i 's/^PASS_MAX_DAYS.*/PASS_MAX_DAYS 99999/' /etc/login.defs && \
    sed -i 's/^PASS_MIN_DAYS.*/PASS_MIN_DAYS 0/' /etc/login.defs && \
    sed -i 's/^PASS_WARN_AGE.*/PASS_WARN_AGE 0/' /etc/login.defs && \
    sed -i 's/^UMASK.*/UMASK 022/' /etc/login.defs

# Set wrong file permissions on shadow files (CIS violations)
RUN chmod 0666 /etc/shadow && \
    chown root:root /etc/shadow && \
    chmod 0666 /etc/gshadow && \
    chown root:root /etc/gshadow

# Create SSH warning banner
RUN echo "Authorized users only. All activity is monitored and recorded." > /etc/issue.net

# Save baseline copies for test restoration
RUN cp /etc/ssh/sshd_config /app/.baseline/sshd_config && \
    cp /etc/ssh/sshd_config.d/90-override.conf /app/.baseline/90-override.conf && \
    cp /etc/sysctl.d/99-insecure.conf /app/.baseline/99-insecure.conf && \
    cp /etc/sysctl.d/50-network.conf /app/.baseline/50-network.conf && \
    cp /etc/login.defs /app/.baseline/login.defs && \
    cp /etc/security/pwquality.conf /app/.baseline/pwquality.conf && \
    cp /etc/security/limits.conf /app/.baseline/limits.conf && \
    cp /etc/sysctl.conf /app/.baseline/sysctl.conf && \
    cp -r /etc/modprobe.d /app/.baseline/modprobe.d

# Copy the broken hardening script
COPY harden.sh /app/harden.sh
RUN chmod +x /app/harden.sh

WORKDIR /app
