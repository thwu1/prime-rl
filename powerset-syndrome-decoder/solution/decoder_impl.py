"""
Minimum-weight syndrome decoder for quantum error correction.

Implements A* search over the power-set graph of errors with an admissible
per-detector cost heuristic and canonical ordering.
"""

import heapq
import math


class SyndromeDecoder:
    """A* search decoder over the power-set graph of errors."""

    def __init__(self, dem_text: str, beam_width: int = 5, pq_limit: int = 200000):
        self._beam_width = beam_width
        self._pq_limit = pq_limit
        self._errors = []  # list of (cost, frozenset(detectors), frozenset(observables))
        self._det_to_errors = {}  # detector -> sorted list of error indices
        self._num_detectors = 0
        self._num_observables = 0
        self._parse(dem_text)
        self._build_index()

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse(self, text: str):
        max_d = -1
        max_o = -1
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith("error("):
                continue
            paren = line.index(")")
            prob = float(line[6:paren])
            rest = line[paren + 1 :].split()
            dets = set()
            obs = set()
            for tok in rest:
                tok = tok.strip()
                if not tok:
                    continue
                if tok.startswith("D"):
                    d = int(tok[1:])
                    dets.add(d)
                    if d > max_d:
                        max_d = d
                elif tok.startswith("L"):
                    o = int(tok[1:])
                    obs.add(o)
                    if o > max_o:
                        max_o = o
            # Skip pure-observable errors and invalid probabilities
            if 0 < prob < 1 and dets:
                cost = -math.log(prob / (1.0 - prob))
                self._errors.append((cost, frozenset(dets), frozenset(obs)))

        self._num_detectors = max_d + 1 if max_d >= 0 else 0
        self._num_observables = max_o + 1 if max_o >= 0 else 0

    def _build_index(self):
        self._det_to_errors = {}
        for i, (c, ds, _) in enumerate(self._errors):
            for d in ds:
                if d not in self._det_to_errors:
                    self._det_to_errors[d] = []
                self._det_to_errors[d].append(i)
        # Sort each list by error cost (ascending) for heuristic efficiency
        for d in self._det_to_errors:
            self._det_to_errors[d].sort(key=lambda i: self._errors[i][0])

    # ------------------------------------------------------------------
    # Heuristic
    # ------------------------------------------------------------------

    def _det_cost(self, d, residual, used):
        """Minimum cost-per-detector for resolving detector d."""
        best = float("inf")
        for ei in self._det_to_errors.get(d, []):
            if ei in used:
                continue
            c, ds, _ = self._errors[ei]
            active = len(ds & residual)
            if active > 0:
                ratio = c / active
                if ratio < best:
                    best = ratio
        return best

    def _heuristic(self, residual, used):
        """Admissible heuristic: sum of per-detector minimum costs."""
        h = 0.0
        for d in residual:
            dc = self._det_cost(d, residual, used)
            if dc == float("inf"):
                return float("inf")
            h += dc
        return h

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------

    def decode(self, syndrome):
        residual = frozenset(syndrome)

        if not residual:
            return {
                "errors": [],
                "observables": [],
                "cost": 0.0,
                "low_confidence": False,
            }

        # Quick feasibility check
        for d in residual:
            if d not in self._det_to_errors or not self._det_to_errors[d]:
                return {
                    "errors": [],
                    "observables": [],
                    "cost": float("inf"),
                    "low_confidence": True,
                }

        h0 = self._heuristic(residual, set())
        if h0 == float("inf"):
            return {
                "errors": [],
                "observables": [],
                "cost": float("inf"),
                "low_confidence": True,
            }

        # Priority queue: (f_cost, tiebreaker, g_cost, residual, error_chain)
        counter = 0
        pq = [(h0, counter, 0.0, residual, ())]
        counter += 1

        min_res_size = len(residual)
        pushed = 0

        while pq:
            f, _, g, res, chain = heapq.heappop(pq)

            # Goal: empty residual
            if not res:
                obs = set()
                for ei in chain:
                    obs ^= self._errors[ei][2]
                return {
                    "errors": sorted(chain),
                    "observables": sorted(obs),
                    "cost": g,
                    "low_confidence": False,
                }

            # Update minimum residual size
            if len(res) < min_res_size:
                min_res_size = len(res)

            # Beam pruning
            if len(res) > min_res_size + self._beam_width:
                continue

            # Canonical ordering: expand only on minimum-index detector
            min_d = min(res)
            used = set(chain)

            for ei in self._det_to_errors.get(min_d, []):
                if ei in used:
                    continue

                c, ds, _ = self._errors[ei]
                ng = g + c

                # Compute new residual via symmetric difference
                nr = res.symmetric_difference(ds)

                # Beam check on successor
                if len(nr) > min_res_size + self._beam_width:
                    continue

                nc = chain + (ei,)
                nu = used | {ei}

                # Compute heuristic for successor
                h = self._heuristic(nr, nu)
                if h == float("inf"):
                    continue

                heapq.heappush(pq, (ng + h, counter, ng, nr, nc))
                counter += 1
                pushed += 1

                if pushed > self._pq_limit:
                    return {
                        "errors": [],
                        "observables": [],
                        "cost": float("inf"),
                        "low_confidence": True,
                    }

        # Queue exhausted without solution
        return {
            "errors": [],
            "observables": [],
            "cost": float("inf"),
            "low_confidence": True,
        }

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def num_errors(self):
        return len(self._errors)

    @property
    def num_detectors(self):
        return self._num_detectors

    @property
    def num_observables(self):
        return self._num_observables
