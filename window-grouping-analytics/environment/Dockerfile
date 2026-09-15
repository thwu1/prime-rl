FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        postgresql \
        postgresql-client \
        python3-pip \
        sudo \
    && rm -rf /var/lib/apt/lists/*

# Configure trust authentication so any local user can connect as postgres
RUN printf 'local all all trust\nhost all all 127.0.0.1/32 trust\nhost all all ::1/128 trust\n' \
    > /etc/postgresql/16/main/pg_hba.conf

# Copy task files
RUN mkdir -p /app/queries
COPY schema.sql /app/schema.sql
COPY queries/q1_hierarchy_cube.sql /app/queries/q1_hierarchy_cube.sql
COPY queries/q2_window_analytics.sql /app/queries/q2_window_analytics.sql
COPY queries/q3_tag_revenue.sql /app/queries/q3_tag_revenue.sql
COPY queries/q4_streak_analysis.sql /app/queries/q4_streak_analysis.sql
COPY queries/q5_peer_comparison.sql /app/queries/q5_peer_comparison.sql
COPY queries/q6_priority_forecast.sql /app/queries/q6_priority_forecast.sql

WORKDIR /app
