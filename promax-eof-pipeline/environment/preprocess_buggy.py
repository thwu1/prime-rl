"""Preprocessing module: area weighting, NaN masking, and centering."""
import numpy as np


def preprocess(data, lats, land_mask):
    """
    Apply area weighting, NaN masking, and centering.

    Parameters
    ----------
    data : ndarray, shape (n_time, n_lat, n_lon)
    lats : ndarray, shape (n_lat,)
    land_mask : ndarray, shape (n_lat, n_lon), boolean

    Returns
    -------
    X_centered : ndarray, shape (n_time, n_valid)
    valid_mask : ndarray, shape (n_lat*n_lon,), boolean
    """
    n_time, n_lat, n_lon = data.shape

    lat_rad = np.deg2rad(lats)
    coslat = np.maximum(np.cos(lat_rad), 0.0)
    coslat_weights = coslat[:, None] * np.ones((1, n_lon))

    weighted = data * coslat_weights[None, :, :]
    flat = weighted.reshape(n_time, -1)

    valid_mask = ~land_mask.ravel()
    X = flat[:, valid_mask]

    temporal_mean = X.mean(axis=0)
    X_centered = X - temporal_mean
    return X_centered, valid_mask
