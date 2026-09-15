FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    lsb-release \
    python3-pip \
    software-properties-common \
    && curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
       -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu noble main" \
       > /etc/apt/sources.list.d/ros2.list \
    && apt-get update && apt-get install -y \
    ros-jazzy-ros-base \
    ros-jazzy-rosidl-default-generators \
    ros-jazzy-ros2lifecycle \
    python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*

RUN echo "source /opt/ros/jazzy/setup.bash" >> /root/.bashrc

COPY ros2_ws /app/ros2_ws
RUN mkdir -p /app/output

WORKDIR /app
