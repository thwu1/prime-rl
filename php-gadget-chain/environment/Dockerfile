FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y \
    apache2 \
    libapache2-mod-php \
    php \
    php-cli \
    curl \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN a2enmod rewrite

COPY apache-ports.conf /etc/apache2/ports.conf
COPY apache-site.conf /etc/apache2/sites-enabled/000-default.conf

RUN rm -f /var/www/html/index.html

COPY app/ /var/www/html/

RUN chown -R www-data:www-data /var/www/html

RUN mkdir -p /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
