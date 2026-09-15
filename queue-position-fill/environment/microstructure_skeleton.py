"""
Market Microstructure Fill Simulation Engine.

Implement by translating queue position models from /app/reference/queue.rs.
See /app/reference/spec.md for behavioral requirements and API.
"""

import math
import numpy as np

# ---- Event flags (hftbacktest event format) ----
DEPTH_EVENT = 1
TRADE_EVENT = 2
DEPTH_SNAPSHOT_EVENT = 4
EXCH_EVENT = 1 << 31
LOCAL_EVENT = 1 << 30
BUY_EVENT = 1 << 29
SELL_EVENT = 1 << 28

# Implement the following (see spec.md Section 8 for the required API):
# - OrderBook
# - RiskAdverseQueueModel
# - ProbQueueModel
# - power_prob_func(n)
# - log_prob_func()
