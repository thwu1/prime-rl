"""Cost-optimal source assignment with affinity constraints.

This module must implement the SourceOptimizer class, which computes
minimum-cost instrument-to-source assignments for each materializable date.

Requirements:
- For each date, every instrument available from any source must be assigned
  to exactly one source that provides it on that date.
- The total cost (sum of per-instrument source costs) must be minimized.
- Affinity group constraints: all instruments in an affinity group that
  appear on a given date must be assigned to the same source. If multiple
  sources can satisfy the group, pick the one with lowest group cost.
- When costs are tied, break ties alphabetically by source name (ascending).
- The optimize_all() method must return assignments for every date where
  at least one source is available.
"""

from dataclasses import dataclass


@dataclass
class DateAssignment:
    """Assignment of instruments to sources for a single date."""
    date: str
    mapping: dict   # {instrument_name: source_name}
    cost: float     # total cost for this date's assignment


class SourceOptimizer:
    """Computes minimum-cost source assignments with affinity constraints.

    Parameters
    ----------
    sources_config : dict
        From loader.get_sources_config(). Maps source names to dicts with
        keys 'instruments' (list[str]), 'available_dates' (list[str]),
        'priority' (int).
    cost_config : dict
        From loader.get_cost_config(). Has keys 'source_costs' (nested dict
        mapping source -> instrument -> float cost) and 'affinity_groups'
        (list of dicts with key 'instruments' listing grouped instrument names).
    """

    def __init__(self, sources_config, cost_config):
        raise NotImplementedError("TODO: implement initialization")

    def optimize_date(self, date):
        """Compute the minimum-cost assignment for a single date.

        Returns
        -------
        DateAssignment
            Contains the instrument-to-source mapping and its total cost.
        """
        raise NotImplementedError("TODO: implement per-date optimization")

    def optimize_all(self):
        """Compute optimal assignments for all materializable dates.

        A date is materializable if at least one source is available on it.

        Returns
        -------
        dict[str, DateAssignment]
            Maps date strings to their optimal DateAssignment.
        """
        raise NotImplementedError("TODO: implement full optimization")

    def total_cost(self):
        """Return the grand total cost across all dates.

        Returns
        -------
        float
        """
        raise NotImplementedError("TODO: implement total cost computation")
