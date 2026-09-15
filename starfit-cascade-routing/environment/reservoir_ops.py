"""Reservoir operating rules for seasonal storage-target release simulation.

This module implements daily reservoir operations based on seasonally-varying
normal operating range (NOR) bounds and storage-dependent release regimes.
Designed for integration with the pywatershed FlowGraph framework — not
directly executable outside the framework runtime.

Adapted from DOI-USGS/pywatershed reservoir modeling components.

Physical processes modeled per timestep, in framework execution order:

  1. **Evaporative loss**: computed from beginning-of-timestep storage
     using the power-law surface area relationship and adjusted PET.
     Surface area (km²) = area_coeff × S_MCM ^ area_exp.
     Volumetric loss (MCM) = area_km2 × adjusted_PET_mm × 1e-3.

  2. **Seepage loss**: computed from beginning-of-timestep storage
     as a proportional daily fraction.
     Volumetric loss (MCM) = seepage_rate × S_MCM.

  3. **Storage adjustment**: both losses are deducted from storage
     BEFORE the release computation. The release function operates
     on the post-loss storage state.

  4. **Release determination**: NOR-based three-regime policy applied
     to the post-loss normalized storage (S_post_loss / capacity).

  5. **Volume balance**: S_new = S_post_loss + (inflow - release) × Δt / 1e6.
     Spill if S_new > capacity; curtailment if S_new < 0.

In the FlowGraph framework, each reservoir node receives its total
inflow as the sum of its local/natural forcing plus the outflow of
every upstream reservoir connected to it via the directed edge list.
Nodes are processed in topological order (upstream before downstream).

Reference:
    Turner, S.W.D., Steyaert, J.C., Condon, L., Voisin, N. (2021).
    Water storage and release policies for all large reservoirs of
    conterminous United States. Journal of Hydrology, 603, Part A.
"""


import numpy as np
from typing import Dict, Tuple

from pywatershed.base.flow_graph import FlowNode
from pywatershed.base.budget import Budget
from pywatershed.base.control import Control

# ────────────────── Unit conversion constants ──────────────────────
# Daily timestep: 86400 seconds
# Volume in MCM (million cubic meters), flow in m³/s
_DT_DAILY = 86400.0
_M3PS_TO_MCM = _DT_DAILY / 1.0e6   # flow (m³/s) × this = volume (MCM)
_MCM_TO_M3PS = 1.0e6 / _DT_DAILY   # volume (MCM) × this = flow (m³/s)


def evaluate_nor_bound(epiweek, amplitude, phase, offset, floor, ceiling):
    """Evaluate a clipped sinusoidal seasonal operating bound.

    Uses the ISO 8601 epidemiological week number (1–53) to compute
    a cosine-based seasonal curve, then clips to [floor, ceiling].

    Parameters are read from the domain parameter dataset.
    Returns a dimensionless fraction of reservoir capacity.
    """
    theta = 2.0 * np.pi * epiweek / 52.0 - phase
    raw = amplitude * np.cos(theta) + offset
    return np.clip(raw, floor, ceiling)


class ReservoirNode(FlowNode):
    """Single reservoir node with seasonal NOR-based release policy.

    The release regime is determined by where the reservoir's normalized
    post-loss storage (S_post_loss / C) falls relative to the current
    NOR bounds for the ISO week of the simulation date.

    Physical losses (evaporation, seepage) are applied by the framework
    driver before calling the release computation. This class handles
    only the release-and-balance step; loss accounting is external.

    The domain parameter dataset must contain all variables listed in
    REQUIRED_PARAMS for each reservoir, plus the evaporation and
    seepage parameters used by the framework driver.
    """

    REQUIRED_PARAMS = (
        'capacity_mcm', 'mean_inflow_cms', 'initial_storage_mcm',
        'area_coeff', 'area_exp', 'pet_adjustment', 'seepage_rate',
        'nor_hi_amplitude', 'nor_hi_phase', 'nor_hi_offset',
        'nor_hi_floor', 'nor_hi_ceiling',
        'nor_lo_amplitude', 'nor_lo_phase', 'nor_lo_offset',
        'nor_lo_floor', 'nor_lo_ceiling',
        'release_flood_max', 'release_flood_scale', 'release_flood_exp',
        'release_flood_base', 'release_normal_coeff',
        'release_conserve_min', 'release_conserve_scale',
        'release_conserve_exp', 'release_conserve_base',
    )

    def __init__(self, control: Control, params: Dict):
        self._control = control
        self._p = params
        self._capacity = params['capacity_mcm']
        self._mean_flow = params['mean_inflow_cms']
        self._storage = float(params['initial_storage_mcm'])

    def _nor_bounds(self, epiweek: int) -> Tuple[float, float]:
        """Compute upper and lower NOR for the given ISO week number."""
        p = self._p
        hi = float(evaluate_nor_bound(
            epiweek,
            p['nor_hi_amplitude'], p['nor_hi_phase'],
            p['nor_hi_offset'], p['nor_hi_floor'], p['nor_hi_ceiling'],
        ))
        lo = float(evaluate_nor_bound(
            epiweek,
            p['nor_lo_amplitude'], p['nor_lo_phase'],
            p['nor_lo_offset'], p['nor_lo_floor'], p['nor_lo_ceiling'],
        ))
        return hi, lo

    def _release_rate(self, s_norm: float, hi: float, lo: float) -> float:
        """Compute release in m³/s given normalized storage s_norm = S / C.

        Three regimes:
          - Above NOR (s_norm > hi): flood release with power-law increase.
            R = flood_max × (flood_scale × (s_norm - hi)^flood_exp
                            + flood_base) × mean_flow
          - Within NOR (lo ≤ s_norm ≤ hi): normal release.
            R = normal_coeff × mean_flow
          - Below NOR (s_norm < lo): conservation release with power-law.
            R = conserve_min × (conserve_scale × (lo - s_norm)^conserve_exp
                               + conserve_base) × mean_flow
        """
        p = self._p
        if s_norm > hi:
            d = s_norm - hi
            r = p['release_flood_max'] * (
                p['release_flood_scale'] * d ** p['release_flood_exp']
                + p['release_flood_base']
            ) * self._mean_flow
        elif s_norm < lo:
            d = lo - s_norm
            r = p['release_conserve_min'] * (
                p['release_conserve_scale'] * d ** p['release_conserve_exp']
                + p['release_conserve_base']
            ) * self._mean_flow
        else:
            r = p['release_normal_coeff'] * self._mean_flow
        return max(0.0, r)

    def advance(self, inflow_cms: float, epiweek: int) -> Dict:
        """Advance one daily timestep (release and volume balance only).

        Assumes physical losses (evaporation, seepage) have already been
        applied to self._storage by the framework driver before this call.
        The release decision therefore reflects the post-loss storage state.

        Args:
            inflow_cms: Total inflow in m³/s, including any upstream
                cascade contributions added by the flow graph.
            epiweek: ISO 8601 week number of the current simulation date.

        Returns:
            Dict with end-of-step state: storage (MCM), release (m³/s),
            spill (m³/s), outflow (m³/s), nor_hi, nor_lo (fractions).
        """
        hi, lo = self._nor_bounds(epiweek)
        release = self._release_rate(self._storage / self._capacity, hi, lo)

        # Volume balance
        s_new = self._storage + (inflow_cms - release) * _M3PS_TO_MCM

        spill = 0.0
        if s_new > self._capacity:
            # Spill excess above capacity
            spill = (s_new - self._capacity) * _MCM_TO_M3PS
            s_new = self._capacity
        elif s_new < 0.0:
            # Curtail release to prevent negative storage
            release += s_new * _MCM_TO_M3PS
            release = max(0.0, release)
            s_new = 0.0

        self._storage = s_new
        return {
            'storage': s_new, 'release': release,
            'spill': spill, 'outflow': release + spill,
            'nor_hi': hi, 'nor_lo': lo,
        }

    @property
    def outflow(self) -> float:
        """Outflow for cascade routing to downstream nodes."""
        return self._last_outflow


# ────────────────── Network routing ──────────────────────────────
# In a FlowGraph, reservoir nodes are processed in topological order
# (upstream before downstream). The network is a directed acyclic
# graph (DAG) where edges represent hydrologic flow connections.
#
# The domain parameter dataset encodes the graph via a list of
# directed edges, each specifying an upstream and downstream
# reservoir ID.
#
# A reservoir may have multiple upstream connections (confluence)
# and its total inflow is:
#   total_inflow = local_forcing + sum(upstream_outflows)
#
# The topological ordering ensures that when a reservoir is processed,
# all its upstream dependencies have already been computed for the
# current timestep. The framework builds this ordering automatically
# from the edge list at initialization time.
