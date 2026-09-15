FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    openssh-server \
    libpam-pwquality \
    auditd \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# --- Set up a system that APPEARS to be STIG-hardened but has 8 subtle defects ---

# SSH: main config looks hardened (PermitRootLogin no, ClientAliveInterval 600)
# but has subtle issues agents must discover
COPY configs/sshd_config /etc/ssh/sshd_config
RUN mkdir -p /etc/ssh/sshd_config.d
COPY configs/50-cloud-init.conf /etc/ssh/sshd_config.d/50-cloud-init.conf

# PAM faillock: faillock.conf has deny=3 (correct)
# but common-auth has inline deny=99 override
COPY configs/faillock.conf /etc/security/faillock.conf
COPY configs/common-auth /etc/pam.d/common-auth

# PAM pwquality: pwquality.conf has minlen=15 (correct)
# but common-password has inline minlen=4 override
COPY configs/pwquality.conf /etc/security/pwquality.conf
COPY configs/common-password /etc/pam.d/common-password

# auditd: most settings correct but max_log_file_action is IGNORE
RUN mkdir -p /etc/audit/rules.d
COPY configs/auditd.conf /etc/audit/auditd.conf

# Audit rules: use legacy auid>=500 instead of modern auid>=1000
COPY configs/privileged.rules /etc/audit/rules.d/privileged.rules

# Shell timeout: set in 00-security-tmout.sh but unset by 99-custom.sh
COPY configs/00-security-tmout.sh /etc/profile.d/00-security-tmout.sh
COPY configs/99-custom.sh /etc/profile.d/99-custom.sh
RUN chmod +x /etc/profile.d/00-security-tmout.sh /etc/profile.d/99-custom.sh

# Kernel ASLR: correct in sysctl.conf but overridden by sysctl.d drop-in
RUN echo "kernel.randomize_va_space = 2" >> /etc/sysctl.conf
RUN mkdir -p /etc/sysctl.d
COPY configs/99-override.conf /etc/sysctl.d/99-override.conf

# Empty banner file (referenced by sshd_config)
RUN touch /etc/issue.net

# Place the controls manifest for the agent
RUN mkdir -p /app
COPY configs/controls.json /app/controls.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
