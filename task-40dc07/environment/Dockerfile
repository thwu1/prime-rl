
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    curl \
    python3-pip \
    ca-certificates \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
       > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install npm dependencies first (cached by package.json changes only)
RUN mkdir -p /app
COPY app/package.json /app/package.json
WORKDIR /app
RUN npm install --production

# Copy application source code after npm install for better Docker layer caching
COPY app/codemods/ /app/codemods/
COPY app/src/ /app/src/

# Verify all expected source files are present
RUN node -e "var fs=require('fs'); ['pricing','checkout','dashboard','analytics','api','notifications','settings','reports'].forEach(function(f){var p='/app/src/'+f+'.js'; if(!fs.existsSync(p)){console.error('MISSING: '+p);process.exit(1);}; console.log('OK: '+p);})"
