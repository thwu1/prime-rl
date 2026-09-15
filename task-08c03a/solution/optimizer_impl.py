"""Cost-optimal source assignment with affinity constraints.

Implements the SourceOptimizer class that computes minimum-cost
instrument-to-source assignments respecting affinity group constraints.

Algorithm:
  For each materializable date:
  1. Determine available sources and required instruments.
  2. Identify active affinity groups (those with >1 required member).
  3. For each active group, enumerate sources that cover ALL group members
     and compute per-source group cost.
  4. Enumerate all combinations of affinity group source assignments.
  5. For each combination, greedily assign remaining (non-affinity)
     instruments to their cheapest available source.
  6. Select the combination yielding minimum total cost.
  7. Ties broken alphabetically by source name (ascending).
"""

from dataclasses import dataclass
from itertools import product as iter_product


@dataclass
class DateAssignment:
    """Assignment of instruments to sources for a single date."""
    date: str
    mapping: dict   # {instrument_name: source_name}
    cost: float     # total cost for this date's assignment


class SourceOptimizer:
    """Computes minimum-cost source assignments with affinity constraints."""

    def __init__(self, sources_config, cost_config):
        self._sources = sources_config
        self._costs = cost_config.get("source_costs", {})
        self._affinity_groups = [
            set(g["instruments"])
            for g in cost_config.get("affinity_groups", [])
        ]

    def _available_on(self, date):
        """Return dict of sources available on a date, mapped to their instrument sets."""
        return {
            name: set(cfg["instruments"])
            for name, cfg in self._sources.items()
            if date in cfg["available_dates"]
        }

    def _inst_cost(self, source, instrument):
        """Look up the cost of assigning an instrument to a source."""
        return self._costs.get(source, {}).get(instrument, float("inf"))

    def _assign_free(self, free_instruments, avail):
        """Greedily assign non-affinity instruments to cheapest source."""
        mapping = {}
        cost = 0.0
        for inst in sorted(free_instruments):
            best_src = None
            best_c = float("inf")
            for src, insts in sorted(avail.items()):
                if inst in insts:
                    c = self._inst_cost(src, inst)
                    if c < best_c or (c == best_c and (best_src is None or src < best_src)):
                        best_src = src
                        best_c = c
            if best_src is not None:
                mapping[inst] = best_src
                cost += best_c
        return mapping, cost

    def optimize_date(self, date):
        """Compute the minimum-cost assignment for a single date."""
        avail = self._available_on(date)
        if not avail:
            return DateAssignment(date=date, mapping={}, cost=0.0)

        # All instruments available on this date
        all_instruments = set()
        for insts in avail.values():
            all_instruments |= insts

        # Identify active affinity groups (those with >1 required member)
        active_groups = []
        affinity_covered = set()
        for group in self._affinity_groups:
            active_members = group & all_instruments
            if len(active_members) > 1:
                active_groups.append(active_members)
                affinity_covered |= active_members

        free_instruments = all_instruments - affinity_covered

        # For each active group, find candidate sources that cover ALL members
        group_candidates = []
        for group in active_groups:
            candidates = []
            for src in sorted(avail.keys()):
                if group <= avail[src]:  # source covers all group members
                    grp_cost = sum(self._inst_cost(src, inst) for inst in group)
                    candidates.append((src, grp_cost))
            # Sort by cost, then alphabetically for tiebreak
            candidates.sort(key=lambda x: (x[1], x[0]))
            group_candidates.append((group, candidates))

        # Compute free instrument assignments
        free_mapping, free_cost = self._assign_free(free_instruments, avail)

        if not group_candidates:
            return DateAssignment(date=date, mapping=free_mapping, cost=free_cost)

        # Enumerate combinations of affinity group assignments
        best_mapping = None
        best_total = float("inf")

        candidate_lists = [cands for _, cands in group_candidates]
        for combo in iter_product(*candidate_lists):
            mapping = dict(free_mapping)
            total = free_cost

            for i, (group, _) in enumerate(group_candidates):
                src, grp_cost = combo[i]
                for inst in group:
                    mapping[inst] = src
                total += grp_cost

            if total < best_total:
                best_total = total
                best_mapping = dict(mapping)
            elif total == best_total and best_mapping is not None:
                # Tiebreak: prefer lexicographically smaller source assignments
                new_key = tuple(
                    mapping.get(inst, "") for inst in sorted(all_instruments)
                )
                old_key = tuple(
                    best_mapping.get(inst, "") for inst in sorted(all_instruments)
                )
                if new_key < old_key:
                    best_mapping = dict(mapping)

        return DateAssignment(date=date, mapping=best_mapping, cost=best_total)

    def optimize_all(self):
        """Compute optimal assignments for all materializable dates."""
        all_dates = set()
        for cfg in self._sources.values():
            for d in cfg["available_dates"]:
                all_dates.add(str(d))

        return {
            date: self.optimize_date(date)
            for date in sorted(all_dates)
        }

    def total_cost(self):
        """Return the grand total cost across all dates."""
        return sum(da.cost for da in self.optimize_all().values())
