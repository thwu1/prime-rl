
"""I/O utilities for loading system configurations and parameters."""
import numpy as np
import configparser


def load_system(npz_path):
    """Load a crystal system from an .npz file.

    Parameters
    ----------
    npz_path : str
        Path to the .npz file containing system data.

    Returns
    -------
    dict with keys:
        positions : ndarray, shape (N, 3)
        charges : ndarray, shape (N,)
        box_length : float
        d : float (nearest-neighbor distance)
        n_particles : int
    """
    data = np.load(npz_path)
    result = {
        'positions': data['positions'].copy(),
        'charges': data['charges'].copy(),
        'box_length': float(data['box_length']),
        'd': float(data['d']),
        'n_particles': int(data['n_particles'])
    }
    data.close()
    return result


def load_parameters(ini_path):
    """Load Ewald parameters from an .ini file.

    Parameters
    ----------
    ini_path : str
        Path to the .ini configuration file.

    Returns
    -------
    dict with keys:
        alpha : float (Ewald splitting parameter)
        k_max : int (maximum k-vector index)
    """
    config = configparser.ConfigParser()
    config.read(ini_path)
    return {
        'alpha': config.getfloat('ewald', 'alpha'),
        'k_max': config.getint('ewald', 'k_max')
    }
