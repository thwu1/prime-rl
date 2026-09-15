"""MWPM decoder for Stim surface code circuits.


Implements minimum-weight perfect matching decoding using PyMatching.
Parses a stim.DetectorErrorModel to construct a weighted matching graph
(nodes = detectors + virtual boundary, edges weighted by log-likelihood
ratios from error mechanisms), and uses Blossom V via PyMatching to find
minimum-weight perfect matchings for batch decoding of detection events
into observable flip predictions.

Edge weights use log-likelihood ratios: w = log((1-p)/p) for error
probability p, so that MWPM finds the most likely error configuration.
"""

import stim
import numpy as np
import pymatching


class StimDecoder:
    """MWPM decoder using Stim's detector error model via PyMatching.

    Constructs a matching graph from the DEM where:
    - Nodes correspond to detectors (syndrome bits) plus a virtual boundary
    - Edges connect pairs of detectors that share an error mechanism,
      weighted by log-likelihood ratios of the corresponding error probs
    - Boundary edges connect single-detector error mechanisms to the
      virtual boundary node
    - Observable tracking follows which logical observables are flipped
      by each error mechanism along matched paths
    """

    def __init__(self, dem):
        self.num_detectors = dem.num_detectors
        self.num_observables = dem.num_observables
        self.matcher = pymatching.Matching.from_detector_error_model(dem)

    def decode_batch(self, detection_events, num_observables=None):
        num_shots = detection_events.shape[0]
        if num_shots == 0:
            n_obs = num_observables if num_observables is not None else self.num_observables
            return np.zeros((0, n_obs), dtype=bool)
        predictions = self.matcher.decode_batch(detection_events)
        return predictions.astype(bool)
