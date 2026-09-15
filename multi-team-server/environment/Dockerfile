FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    acl \
    cron \
    sudo \
    systemd \
    passwd \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Create functional groups
RUN groupadd -f wheel && groupadd -f developers && groupadd -f monitoring && groupadd -f deploy && groupadd -f backup

# Create human users
RUN useradd -m -u 1100 -G wheel -s /bin/bash admin && \
    useradd -m -u 1300 -G developers -s /bin/bash developer1 && \
    useradd -m -u 1301 -G developers -s /bin/bash developer2 && \
    useradd -m -u 1302 -G developers -s /bin/bash webadmin

# Create service accounts with intentional misconfigurations
RUN useradd -m -u 1200 -G monitoring -s /bin/bash svc_monitor && \
    useradd -m -u 1201 -G deploy,wheel -s /usr/sbin/nologin svc_deploy && \
    useradd -m -u 1202 -G backup -s /bin/bash svc_backup

# Set up /opt/scripts with wrong ownership and a dangerous SUID script
RUN mkdir -p /opt/scripts /opt/data /var/log/app /var/backups /app/scripts && \
    chown admin:admin /opt/scripts && \
    printf '#!/bin/bash\necho "deploying application..."\n' > /opt/scripts/deploy.sh && \
    chmod 4777 /opt/scripts/deploy.sh && \
    cp /etc/shadow /var/backups/shadow.bak && \
    chmod 0644 /var/backups/shadow.bak && \
    chmod 1777 /var/log/app && \
    printf 'legacy configuration data\n' > /opt/data/config.dat && \
    chown 1337:1337 /opt/data/config.dat

# Install broken sudo configurations
COPY sudoers_developers /etc/sudoers.d/developers
COPY sudoers_monitoring /etc/sudoers.d/monitoring
COPY sudoers_deploy /etc/sudoers.d/deploy
COPY sudoers_env_config /etc/sudoers.d/env-config
RUN chmod 0440 /etc/sudoers.d/developers /etc/sudoers.d/monitoring /etc/sudoers.d/env-config && \
    chmod 0644 /etc/sudoers.d/deploy && \
    chown root:root /etc/sudoers.d/developers /etc/sudoers.d/monitoring /etc/sudoers.d/env-config /etc/sudoers.d/deploy

# Set up insecure cron job (root executes from /tmp)
COPY system-backup.cron /etc/cron.d/system-backup
RUN chmod 0644 /etc/cron.d/system-backup && \
    printf '#!/bin/bash\ntar czf /var/backups/full.tar.gz /opt/ 2>/dev/null\n' > /tmp/run_backup.sh && \
    chmod 755 /tmp/run_backup.sh

# Set up insecure systemd units (service runs script from user home dir)
COPY app-maintenance.service /etc/systemd/system/app-maintenance.service
COPY app-maintenance.timer /etc/systemd/system/app-maintenance.timer
RUN mkdir -p /home/admin/scripts && \
    printf '#!/bin/bash\nfind /var/log -name "*.old" -delete 2>/dev/null\n' > /home/admin/scripts/maintenance.sh && \
    chmod 755 /home/admin/scripts/maintenance.sh && \
    chown -R admin:admin /home/admin/scripts

# Set up admin's insecure crontab (weakens log directory permissions every 5 min)
RUN printf '*/5 * * * * chmod -R 777 /var/log/app/\n' | crontab -u admin -

# Configure insecure system-wide password policies
RUN sed -i 's/^PASS_MAX_DAYS.*/PASS_MAX_DAYS\t99999/' /etc/login.defs && \
    sed -i 's/^PASS_MIN_DAYS.*/PASS_MIN_DAYS\t0/' /etc/login.defs && \
    sed -i 's/^PASS_WARN_AGE.*/PASS_WARN_AGE\t7/' /etc/login.defs

# Copy policy documents into the working directory
COPY audit-report.txt /app/audit-report.txt
COPY security-policy.txt /app/security-policy.txt

WORKDIR /app
