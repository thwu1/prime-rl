"""Partition reconciliation engine — solution implementation."""

from typing import Dict, Set, List
from dataclasses import dataclass, field


@dataclass
class ReconciliationPlan:
    materializable: Set[str] = field(default_factory=set)
    source_coverage: Dict[str, Set[str]] = field(default_factory=dict)
    fully_covered: Set[str] = field(default_factory=set)
    partially_covered: Set[str] = field(default_factory=set)
    instrument_source_map: Dict[str, Dict[str, str]] = field(default_factory=dict)


class PartitionReconciler:
    def __init__(self, sources_config: dict):
        self._config = sources_config

    def get_available_partition_keys(self, source_name: str) -> Set[str]:
        cfg = self._config[source_name]
        keys: Set[str] = set()
        for inst in cfg["instruments"]:
            for date in cfg["available_dates"]:
                keys.add(f"{inst}|{date}")
        return keys

    def get_all_dates(self) -> Set[str]:
        dates: Set[str] = set()
        for cfg in self._config.values():
            dates.update(cfg["available_dates"])
        return dates

    def get_all_instruments(self) -> Set[str]:
        instruments: Set[str] = set()
        for cfg in self._config.values():
            instruments.update(cfg["instruments"])
        return instruments

    def get_coverage_matrix(self) -> Dict[str, Dict[str, Set[str]]]:
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
                            new_pri == current_pri and src_name < inst_map[inst]
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
