FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install task environment packages
RUN apt-get update && apt-get install -y \
    libpam-modules \
    libpam-pwquality \
    libpam0g-dev \
    python3-pip \
    passwd \
    login \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set up users and groups
COPY setup_users.sh /tmp/setup_users.sh
RUN bash /tmp/setup_users.sh && rm /tmp/setup_users.sh

# Deploy broken PAM configuration files
COPY broken_common_auth /etc/pam.d/common-auth
COPY broken_common_account /etc/pam.d/common-account
COPY broken_common_session /etc/pam.d/common-session
COPY broken_common_password /etc/pam.d/common-password
COPY broken_su /etc/pam.d/su

# Deploy broken security parameter files
COPY broken_faillock_conf /etc/security/faillock.conf
COPY broken_limits_conf /etc/security/limits.conf
COPY broken_access_conf /etc/security/access.conf
COPY broken_pwquality_conf /etc/security/pwquality.conf

# Deploy incident evidence and requirements
COPY auth_log.txt /app/auth_log.txt
COPY incident_report.txt /app/incident_report.txt
COPY operational_requirements.txt /app/operational_requirements.txt

WORKDIR /app
