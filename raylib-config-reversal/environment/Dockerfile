FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install build dependencies for raylib (desktop GLFW on Linux)
RUN apt-get update && apt-get install -y \
    gcc \
    make \
    git \
    binutils \
    libx11-dev \
    libxrandr-dev \
    libxinerama-dev \
    libxcursor-dev \
    libxi-dev \
    mesa-common-dev \
    libgl-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Clone raylib source (unmodified reference for the agent)
RUN git clone --depth 1 https://github.com/raysan5/raylib.git /app/raylib

# Generate the test input image (pure Python, no external deps)
COPY generate_input.py /tmp/generate_input.py
RUN python3 /tmp/generate_input.py && rm /tmp/generate_input.py

# Build the target library with a custom (hidden) configuration
COPY patch_config.py /tmp/patch_config.py
COPY build_target.sh /tmp/build_target.sh
RUN bash /tmp/build_target.sh && rm /tmp/build_target.sh /tmp/patch_config.py

# Hide the config that was used to build the target (move to non-obvious location)
RUN mv /app/target/config.h.hidden /var/lib/.raylib_target_config.h && \
    chmod 400 /var/lib/.raylib_target_config.h

# Copy the task specification
COPY spec.md /app/spec.md

# Create output directories
RUN mkdir -p /app/output /app/analysis

WORKDIR /app
