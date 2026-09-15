"""Minimum-weight syndrome decoder for quantum error correction."""


class SyndromeDecoder:
    def __init__(self, dem_text: str, beam_width: int = 5, pq_limit: int = 200000):
        raise NotImplementedError

    def decode(self, syndrome: list[int]) -> dict:
        raise NotImplementedError

    @property
    def num_errors(self) -> int:
        raise NotImplementedError

    @property
    def num_detectors(self) -> int:
        raise NotImplementedError

    @property
    def num_observables(self) -> int:
        raise NotImplementedError
