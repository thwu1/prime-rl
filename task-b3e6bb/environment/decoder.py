"""Surface code decoder using Stim's detector error model.


Implement the StimDecoder class below. It must accept a
stim.DetectorErrorModel and decode detection event samples into
predicted observable flip arrays.

Examine the circuit files in /app/circuits/ and the detector error
model structure to determine a suitable decoding strategy.
"""

import numpy as np


class StimDecoder:
    """Decoder that operates on Stim's detector error model."""

    def __init__(self, dem):
        """Initialize decoder from a detector error model.

        Args:
            dem: stim.DetectorErrorModel extracted from a circuit.
        """
        raise NotImplementedError("StimDecoder not yet implemented")

    def decode_batch(self, detection_events, num_observables=None):
        """Decode a batch of detection event samples.

        Args:
            detection_events: bool array of shape (num_shots, num_detectors)
            num_observables: ignored (uses value from DEM)

        Returns:
            bool array of shape (num_shots, num_observables)
        """
        raise NotImplementedError("StimDecoder not yet implemented")
