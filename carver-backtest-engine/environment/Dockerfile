FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 pandas==2.2.3 pyyaml==6.0.2

COPY setup_data.py /tmp/setup_data.py
RUN mkdir -p /app && python3 /tmp/setup_data.py && rm /tmp/setup_data.py

COPY system_config.yaml /app/system_config.yaml
COPY run_backtest.py /app/run_backtest.py
RUN mkdir -p /app/trading_system
COPY trading_system/__init__.py /app/trading_system/__init__.py
COPY trading_system/config.py /app/trading_system/config.py
COPY trading_system/data_loader.py /app/trading_system/data_loader.py
COPY trading_system/volatility.py /app/trading_system/volatility.py
COPY trading_system/signals.py /app/trading_system/signals.py
COPY trading_system/forecast.py /app/trading_system/forecast.py
COPY trading_system/positions.py /app/trading_system/positions.py

WORKDIR /app
