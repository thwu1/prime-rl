#!/usr/bin/env python3
"""Generate calibration data for the quantization pipeline task."""

import numpy as np



def main():
    np.random.seed(123)
    # 50 calibration samples, each with batch dim 1
    data = np.random.randn(50, 1, 3, 32, 32).astype(np.float32)
    np.save("/app/calibration_data.npy", data)
    print("Calibration data saved to /app/calibration_data.npy")
    print(f"Shape: {data.shape}, dtype: {data.dtype}")


if __name__ == "__main__":
    main()
