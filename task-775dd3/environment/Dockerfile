FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install build dependencies, PHP-FPM, and runtime tools
RUN apt-get update && apt-get install -y \
    build-essential wget curl \
    libapr1-dev libaprutil1-dev libpcre2-dev libssl-dev \
    libnghttp2-dev libjansson-dev libcurl4-openssl-dev \
    php8.3-fpm php8.3-cli \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Build flag generator (source deleted after compilation)
COPY src/flaggen.c /tmp/flaggen.c
RUN gcc -O2 /tmp/flaggen.c -o /usr/local/bin/flaggen -lcrypto -s && rm -f /tmp/flaggen.c

# Compile Apache 2.4.59 from source
RUN cd /tmp && \
    wget -q --tries=3 --timeout=60 \
        https://archive.apache.org/dist/httpd/httpd-2.4.59.tar.gz && \
    tar xzf httpd-2.4.59.tar.gz && \
    cd httpd-2.4.59 && \
    ./configure --prefix=/usr/local/apache2 \
        --with-mpm=prefork \
        --enable-mpms-shared=prefork \
        --enable-mods-shared=all \
        --enable-rewrite \
        --enable-proxy \
        --enable-proxy-fcgi \
        --enable-so && \
    make -j$(nproc) && \
    make install && \
    rm -rf /tmp/httpd*

# Create required directories
RUN mkdir -p /var/www/html /var/secret \
    /usr/share/doc/webapp-utils/tools \
    /run/php /app \
    /usr/local/apache2/logs

# Deploy PHP-FPM pool config (use TCP for reliable proxy:fcgi:// handling)
COPY conf/php-fpm-pool.conf /etc/php/8.3/fpm/pool.d/www.conf

# Deploy Apache configuration
COPY conf/httpd.conf /usr/local/apache2/conf/httpd.conf
COPY conf/vhost.conf /usr/local/apache2/conf/extra/vhost.conf

# Back up original vhost config for test restoration
RUN cp /usr/local/apache2/conf/extra/vhost.conf /usr/local/apache2/conf/extra/vhost.conf.original

# Deploy web application
COPY www/index.html /var/www/html/index.html
COPY www/credentials.php /var/www/html/credentials.php

# Deploy utility (simulates a common package-installed PHP tool)
COPY tools/reader.php /usr/share/doc/webapp-utils/tools/reader.php

# Deploy startup script
COPY scripts/setup.sh /app/setup.sh
RUN chmod +x /app/setup.sh

# Set ownership
RUN chown -R www-data:www-data /var/www/html && \
    chown -R www-data:www-data /usr/share/doc/webapp-utils

# Verify Apache config syntax at build time
RUN /usr/local/apache2/bin/httpd -t 2>&1 || \
    (cat /usr/local/apache2/logs/error_log 2>/dev/null; exit 1)

WORKDIR /app
