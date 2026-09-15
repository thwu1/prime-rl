import numpy as np
import stim
import pymatching

try:
    from ldpc import BpDecoder

    def _create_bp_decoder(pcm, priors, **kwargs):
        return BpDecoder(pcm=pcm, error_channel=list(priors), **kwargs)
except ImportError:
    from ldpc import bp_decoder as _bp_decoder_cls

    def _create_bp_decoder(pcm, priors, **kwargs):
        return _bp_decoder_cls(
            parity_check_matrix=pcm, channel_probs=list(priors), **kwargs
        )

from dem_to_matrices import detector_error_model_to_check_matrices


class SyndromeDecoder:
    """Syndrome decoder: uses soft information with MWPM fallback."""

    def __init__(
        self,
        dem: stim.DetectorErrorModel,
    ):
        self._matrices = detector_error_model_to_check_matrices(dem)
        self._bpd = _create_bp_decoder(
            pcm=self._matrices.check_matrix,
            priors=self._matrices.priors,
            max_iter=20,
            bp_method="product_sum",
            input_vector_type="syndrome",
        )

    def decode(self, syndrome: np.ndarray) -> np.ndarray:
        """Decode a single syndrome and return observable predictions."""
        corr = self._bpd.decode(syndrome)
        if self._bpd.converge:
            return (self._matrices.observables_matrix @ corr) % 2

        # BP did not converge: extract soft info and fall back to MWPM
        llrs = self._bpd.log_prob_ratios
        ps_h = 1.0 / (1.0 + np.exp(llrs))
        ps_e = self._matrices.hyperedge_to_edge_matrix @ ps_h
        eps = 1e-14
        ps_e = np.clip(ps_e, eps, 1.0 - eps)

        matching = pymatching.Matching.from_check_matrix(
            self._matrices.edge_check_matrix,
            weights=-np.log(ps_e),
            faults_matrix=self._matrices.edge_observables_matrix,
            use_virtual_boundary_node=True,
        )
        return matching.decode(syndrome)

    def decode_batch(self, shots: np.ndarray) -> np.ndarray:
        """Decode a batch of syndromes."""
        n_obs = self._matrices.observables_matrix.shape[0]
        predictions = np.zeros((shots.shape[0], n_obs), dtype=bool)
        for i in range(shots.shape[0]):
            predictions[i, :] = self.decode(shots[i, :])
        return predictions
