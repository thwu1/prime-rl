"""Source configuration for the multi-provider market data pipeline."""

SOURCES_CONFIG = {
    "alpha": {
        "instruments": ["AAPL", "GOOGL", "MSFT"],
        "available_dates": [
            "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
        ],
        "priority": 1,
    },
    "beta": {
        "instruments": ["AAPL", "MSFT", "TSLA"],
        "available_dates": [
            "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06", "2024-01-07",
        ],
        "priority": 2,
    },
    "gamma": {
        "instruments": ["GOOGL", "TSLA", "AMZN"],
        "available_dates": [
            "2024-01-01", "2024-01-02", "2024-01-06", "2024-01-07", "2024-01-08",
        ],
        "priority": 3,
    },
}
