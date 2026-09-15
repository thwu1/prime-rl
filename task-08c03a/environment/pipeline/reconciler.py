"""Partition reconciliation engine.

Determines which partitions of downstream assets can be materialized
given the available partitions of upstream source assets.
"""

from typing import Dict, Set
from dataclasses import dataclass, field


@dataclass
class ReconciliationPlan:
    """Results of partition reconciliation across sources."""

    materializable: Set[str] = field(default_factory=set)
    source_coverage: Dict[str, Set[str]] = field(default_factory=dict)
    fully_covered: Set[str] = field(default_factory=set)
    partially_covered: Set[str] = field(default_factory=set)
    instrument_source_map: Dict[str, Dict[str, str]] = field(default_factory=dict)


class PartitionReconciler:
    """Reconciles partitions across multiple data sources.

    Given a set of sources -- each with its own instruments, available
    dates, and priority -- this class computes which downstream date
    partitions can be materialized, which sources contribute data for
    each date, and the optimal source for each (instrument, date) pair
    based on priority (lowest number = highest priority; ties broken
    alphabetically by source name -- earliest name wins).
    """

    def __init__(self, sources_config: dict):
        self._config = sources_config

    def get_available_partition_keys(self, source_name: str) -> Set[str]:
        """Return all composite partition keys for a source.
        Each key has the form '{instrument}|{date}'.
        """
        cfg = self._config[source_name]
        keys: Set[str] = set()
        for inst in cfg["instruments"]:
            for date in cfg["available_dates"]:
                keys.add(f"{inst}|{date}")
        return keys

    def get_all_dates(self) -> Set[str]:
        """Return the union of all dates across all sources."""
        dates: Set[str] = set()
        for cfg in self._config.values():
            dates.update(cfg["available_dates"])
        return dates

    def get_all_instruments(self) -> Set[str]:
        """Return the union of all instruments across all sources."""
        instruments: Set[str] = set()
        for cfg in self._config.values():
            instruments.update(cfg["instruments"])
        return instruments

    def get_coverage_matrix(self) -> Dict[str, Dict[str, Set[str]]]:
        """Return the full coverage matrix.

        Maps each date to a dict mapping each instrument to the set of
        source names that provide data for that (date, instrument) pair.
        """
        matrix: Dict[str, Dict[str, Set[str]]] = {}
        for date in self.get_all_dates():
            matrix[date] = {}
            for src_name, cfg in self._config.items():
                if date in cfg["available_dates"]:
                    for inst in cfg["instruments"]:
                        if inst not in matrix[date]:
                            matrix[date][inst] = set()
                        matrix[date][inst].add(src_name)
        return matrix

    def reconcile(self) -> ReconciliationPlan:
        """Generate a reconciliation plan."""
        all_dates = self.get_all_dates()
        source_names = set(self._config.keys())

        materializable: Set[str] = set()
        source_coverage: Dict[str, Set[str]] = {}
        fully_covered: Set[str] = set()
        partially_covered: Set[str] = set()
        instrument_source_map: Dict[str, Dict[str, str]] = {}

        for date in all_dates:
            covering_sources: Set[str] = set()
            for src_name, cfg in self._config.items():
                if date in cfg["available_dates"]:
                    covering_sources.add(src_name)

            if not covering_sources:
                continue

            materializable.add(date)
            source_coverage[date] = covering_sources

            if covering_sources == source_names:
                fully_covered.add(date)
            else:
                partially_covered.add(date)

            inst_map: Dict[str, str] = {}
            for src_name in covering_sources:
                cfg = self._config[src_name]
                for inst in cfg["instruments"]:
                    if inst not in inst_map:
                        inst_map[inst] = src_name
                    else:
                        current_pri = self._config[inst_map[inst]]["priority"]
                        new_pri = cfg["priority"]
                        if new_pri < current_pri or (
                            new_pri == current_pri and src_name > inst_map[inst]
                        ):
                            inst_map[inst] = src_name
            instrument_source_map[date] = inst_map

        return ReconciliationPlan(
            materializable=materializable,
            source_coverage=source_coverage,
            fully_covered=fully_covered,
            partially_covered=partially_covered,
            instrument_source_map=instrument_source_map,
        )
