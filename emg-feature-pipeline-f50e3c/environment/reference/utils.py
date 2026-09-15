import numpy as np

def get_windows(data, window_size, window_increment, channel_last=False):
    """Extracts windows from a given set of data.

    Parameters
    ----------
    data: list
        An NxM stream of data with N samples and M channels
    window_size: int
        The number of samples in a window.
    window_increment: int
        The number of samples that advances before next window.
    channel_last: bool, default=False
        Output will be NxLxC if True. By default the LibEMG feature extractor assumes default is False.

    Returns
    ----------
    list
        The set of windows extracted from the data as a NxCxL where N is the number of windows, C is the number of channels
        and L is the length of each window. Output will be NxLxC if channel_last is True.

    Examples
    ---------
    >>> data = np.loadtxt('data.csv', delimiter=',')
    >>> windows = get_windows(data, 100, 50)
    """
    data = np.array(data)
    if data.ndim == 1:
        data = np.expand_dims(data, axis=-1)

    T = data.shape[0]
    starts = np.arange(0, T - window_size + 1, window_increment)
    idx = starts[:, None] + np.arange(window_size)[None, :]

    windows = data[idx]
    if not channel_last:
        windows = np.transpose(windows, (0, 2, 1))

    return windows

def _get_mode_windows(data, window_size, window_increment):
    windows = get_windows(data, window_size, window_increment)
    mode_of_windows = np.apply_along_axis(lambda x: np.bincount(x).argmax(), axis=2, arr=windows.astype(np.int64))
    return mode_of_windows.squeeze()
