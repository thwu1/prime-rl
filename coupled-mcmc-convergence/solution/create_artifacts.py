"""Create analysis.sql and optimal_proposal.npy artifacts.

"""
import numpy as np

# === Create /app/analysis.sql ===
analysis_sql = """\
-- QUERY 1
WITH avg_stats AS (
    SELECT target, config, AVG(meeting_time) AS mean_mt
    FROM results
    GROUP BY target, config
),
ranked AS (
    SELECT target, config, mean_mt,
           ROW_NUMBER() OVER (PARTITION BY target ORDER BY mean_mt, config) AS rn
    FROM avg_stats
)
SELECT target, config AS best_config, ROUND(mean_mt, 4) AS mean_meeting_time
FROM ranked WHERE rn = 1;

-- QUERY 2
WITH chain_data AS (
    SELECT config, meeting_time,
           ROW_NUMBER() OVER (PARTITION BY config ORDER BY meeting_time) AS rn,
           COUNT(*) OVER (PARTITION BY config) AS cnt
    FROM results
    WHERE target = 'correlated_8d'
),
medians AS (
    SELECT config, AVG(meeting_time) AS median_meeting_time
    FROM chain_data
    WHERE rn IN (cnt / 2, cnt / 2 + 1)
    GROUP BY config
)
SELECT config, ROUND(median_meeting_time, 1) AS median_meeting_time,
       ROW_NUMBER() OVER (ORDER BY median_meeting_time) AS rank
FROM medians;

-- QUERY 3
WITH config_rates AS (
    SELECT target, config, AVG(x_accept_rate) AS mean_accept
    FROM results
    GROUP BY target, config
)
SELECT target, ROUND(MAX(mean_accept) - MIN(mean_accept), 6) AS accept_spread
FROM config_rates
GROUP BY target;
"""

with open("/app/analysis.sql", "w") as f:
    f.write(analysis_sql)
print("Created /app/analysis.sql")

# === Create /app/optimal_proposal.npy ===
# The correlated_8d target has covariance 0.3*I + 0.7*ones(8,8).
# Optimal RWM proposal scale is (2.38^2 / d) * Sigma_target.
dim = 8
target_cov = 0.3 * np.eye(dim) + 0.7 * np.ones((dim, dim))
optimal_proposal = (2.38 ** 2 / dim) * target_cov
np.save("/app/optimal_proposal.npy", optimal_proposal)
print(f"Created /app/optimal_proposal.npy, shape={optimal_proposal.shape}")
print(f"Eigenvalues: {np.sort(np.linalg.eigvalsh(optimal_proposal))}")
