"""Validation script for the partition reconciliation pipeline.

Runs comprehensive checks on the reconciliation system.
All checks must pass for the pipeline to be considered correct.
"""

import sys

sys.path.insert(0, "/app")

from pipeline.loader import get_sources_config, get_db_instruments, get_backfill_config, get_cost_config
from pipeline.reconciler import PartitionReconciler
from pipeline.planner import AssetNode, build_execution_plan


def main():
    failures = []

    # Load config
    try:
        sources_config = get_sources_config()
    except Exception as e:
        print(f"FATAL: Failed to load sources config: {e}")
        sys.exit(1)

    # -------------------------------------------------------------------
    # CHECK 1: All five sources should be present
    # -------------------------------------------------------------------
    expected_sources = {"alpha", "beta", "gamma", "delta", "epsilon"}
    actual_sources = set(sources_config.keys())
    if actual_sources != expected_sources:
        failures.append(
            f"CHECK 1: expected sources {sorted(expected_sources)}, "
            f"got {sorted(actual_sources)}"
        )

    # -------------------------------------------------------------------
    # CHECK 2: All config values must be strings
    # -------------------------------------------------------------------
    for src_name, cfg in sources_config.items():
        for inst in cfg.get("instruments", []):
            if not isinstance(inst, str):
                failures.append(
                    f"CHECK 2 ({src_name}): instrument {inst!r} is "
                    f"{type(inst).__name__}, expected str"
                )
        for date in cfg.get("available_dates", []):
            if not isinstance(date, str):
                failures.append(
                    f"CHECK 2 ({src_name}): date {date!r} is "
                    f"{type(date).__name__}, expected str"
                )

    # -------------------------------------------------------------------
    # CHECK 3: YAML instruments must match DB instruments per source
    # -------------------------------------------------------------------
    for src_name in sources_config:
        yaml_insts = set(
            str(i) for i in sources_config[src_name].get("instruments", [])
        )
        db_insts = set(get_db_instruments(src_name))
        if yaml_insts != db_insts:
            failures.append(
                f"CHECK 3 ({src_name}): YAML instruments {sorted(yaml_insts)} "
                f"!= DB instruments {sorted(db_insts)}"
            )

    # -------------------------------------------------------------------
    # CHECK 4: Reconciliation checks
    # -------------------------------------------------------------------
    plan = None
    try:
        reconciler = PartitionReconciler(sources_config)
        plan = reconciler.reconcile()
    except Exception as e:
        failures.append(f"CHECK 4: Reconciler failed: {e}")

    if plan:
        # 4a: All 9 dates should be materializable
        expected_dates = {f"2024-01-0{i}" for i in range(1, 10)}
        if plan.materializable != expected_dates:
            failures.append(
                f"CHECK 4a: expected {len(expected_dates)} materializable dates, "
                f"got {len(plan.materializable)}: "
                f"{sorted(str(d) for d in plan.materializable)}"
            )

        # 4b: Source coverage for specific dates
        expected_coverage = {
            "2024-01-01": {"alpha", "gamma"},
            "2024-01-03": {"alpha", "beta", "delta"},
            "2024-01-05": {"alpha", "beta", "delta", "epsilon"},
            "2024-01-06": {"beta", "gamma", "delta", "epsilon"},
            "2024-01-09": {"epsilon"},
        }
        for date, expected_src in expected_coverage.items():
            actual_src = plan.source_coverage.get(date, set())
            if actual_src != expected_src:
                failures.append(
                    f"CHECK 4b ({date}): expected coverage "
                    f"{sorted(expected_src)}, got {sorted(str(s) for s in actual_src)}"
                )

        # 4c: Priority-based source selection with alphabetical tiebreak
        checks_4c = [
            ("2024-01-05", "MSFT", "alpha"),
            ("2024-01-06", "MSFT", "epsilon"),
            ("2024-01-05", "NFLX", "epsilon"),
            ("2024-01-05", "TSLA", "epsilon"),
            ("2024-01-03", "0050", "delta"),
            ("2024-01-06", "AMZN", "delta"),
        ]
        for date, instrument, expected_source in checks_4c:
            ism = plan.instrument_source_map.get(date, {})
            actual_source = ism.get(instrument)
            if actual_source != expected_source:
                failures.append(
                    f"CHECK 4c ({instrument}, {date}): expected source "
                    f"'{expected_source}', got '{actual_source}'"
                )

    # -------------------------------------------------------------------
    # CHECK 5: Backfill execution plan
    # -------------------------------------------------------------------
    if plan and plan.materializable == {f"2024-01-0{i}" for i in range(1, 10)}:
        backfill_cfg = get_backfill_config()
        all_dates = sorted(plan.materializable)
        assets_cfg = backfill_cfg.get("assets", {})
        nodes = {}
        for asset_name, asset_def in assets_cfg.items():
            nodes[asset_name] = AssetNode(
                key=asset_name,
                partition_keys=all_dates,
                dependencies=asset_def.get("dependencies", []),
                sequential=asset_def.get("sequential", False),
            )

        concurrency = backfill_cfg.get("concurrency_limit", 1)
        waves = None
        try:
            waves = build_execution_plan(nodes, concurrency_limit=concurrency)
        except Exception as e:
            failures.append(f"CHECK 5: Planner failed: {e}")

        if waves is not None:
            total_steps = sum(len(w) for w in waves)
            expected_steps = len(all_dates) * len(nodes)
            if total_steps != expected_steps:
                failures.append(
                    f"CHECK 5a: expected {expected_steps} total steps, "
                    f"got {total_steps}"
                )

            all_steps = [s for w in waves for s in w]
            raw_idx = [
                i for i, s in enumerate(all_steps) if s.asset_key == "raw_prices"
            ]
            enr_idx = [
                i
                for i, s in enumerate(all_steps)
                if s.asset_key == "enriched_prices"
            ]
            ana_idx = [
                i for i, s in enumerate(all_steps) if s.asset_key == "analytics"
            ]

            if raw_idx and enr_idx and max(raw_idx) >= min(enr_idx):
                failures.append(
                    "CHECK 5b: raw_prices not fully before enriched_prices"
                )
            if enr_idx and ana_idx and max(enr_idx) >= min(ana_idx):
                failures.append(
                    "CHECK 5b: enriched_prices not fully before analytics"
                )

            if raw_idx:
                raw_steps = [all_steps[i] for i in raw_idx]
                raw_dates = [s.partition_key for s in raw_steps]
                if raw_dates != sorted(raw_dates):
                    failures.append(
                        "CHECK 5c: raw_prices partitions not in sequential order"
                    )

            for wi, wave in enumerate(waves):
                if len(wave) > concurrency:
                    failures.append(
                        f"CHECK 5d: wave {wi} has {len(wave)} steps, "
                        f"exceeds concurrency limit {concurrency}"
                    )

    # -------------------------------------------------------------------
    # CHECK 6: Cost-optimal source assignment (optimizer)
    # -------------------------------------------------------------------
    if plan and plan.materializable == {f"2024-01-0{i}" for i in range(1, 10)}:
        opt_result = None
        try:
            cost_config = get_cost_config()
            from pipeline.optimizer import SourceOptimizer
            optimizer = SourceOptimizer(sources_config, cost_config)
            opt_result = optimizer.optimize_all()
        except Exception as e:
            failures.append(f"CHECK 6: Optimizer failed: {e}")

        if opt_result is not None:
            # 6a: All materializable dates must have assignments
            opt_dates = set(opt_result.keys())
            if opt_dates != plan.materializable:
                failures.append(
                    f"CHECK 6a: optimizer dates {sorted(opt_dates)} "
                    f"!= materializable {sorted(plan.materializable)}"
                )

            # 6b: Every instrument on every date must be validly assigned
            for date_str in sorted(opt_result.keys()):
                da = opt_result[date_str]
                for inst, src in da.mapping.items():
                    src_cfg = sources_config.get(src)
                    if src_cfg is None:
                        failures.append(
                            f"CHECK 6b ({date_str}): unknown source '{src}'"
                        )
                    elif date_str not in src_cfg["available_dates"]:
                        failures.append(
                            f"CHECK 6b ({date_str}): source '{src}' not available"
                        )
                    elif inst not in src_cfg["instruments"]:
                        failures.append(
                            f"CHECK 6b ({date_str}): source '{src}' "
                            f"does not have instrument '{inst}'"
                        )

            # 6c: All required instruments must be assigned
            for date_str in sorted(opt_result.keys()):
                expected_insts = set()
                for src, cfg in sources_config.items():
                    if date_str in cfg["available_dates"]:
                        expected_insts.update(cfg["instruments"])
                actual_insts = set(opt_result[date_str].mapping.keys())
                if actual_insts != expected_insts:
                    failures.append(
                        f"CHECK 6c ({date_str}): assigned instruments "
                        f"{sorted(actual_insts)} != required {sorted(expected_insts)}"
                    )

            # 6d: Affinity constraints must be respected
            for date_str, da in opt_result.items():
                for group in cost_config.get("affinity_groups", []):
                    grp_insts = set(group["instruments"])
                    assigned_from_group = {
                        i: da.mapping[i] for i in grp_insts if i in da.mapping
                    }
                    if len(assigned_from_group) > 1:
                        sources_used = set(assigned_from_group.values())
                        if len(sources_used) > 1:
                            failures.append(
                                f"CHECK 6d ({date_str}): affinity group "
                                f"{sorted(grp_insts)} split across "
                                f"{sorted(sources_used)}"
                            )

            # 6e: Total cost must be optimal
            total = sum(da.cost for da in opt_result.values())
            if abs(total - 60.0) > 0.01:
                failures.append(
                    f"CHECK 6e: total cost {total:.4f} != expected 60.0"
                )

            # 6f: Verify specific assignments where affinity binds
            specific_checks = [
                ("2024-01-03", "AAPL", "beta"),
                ("2024-01-03", "MSFT", "beta"),
                ("2024-01-04", "AAPL", "beta"),
                ("2024-01-05", "AAPL", "beta"),
                ("2024-01-05", "MSFT", "beta"),
                ("2024-01-01", "GOOGL", "gamma"),
                ("2024-01-05", "TSLA", "epsilon"),
                ("2024-01-06", "AMZN", "gamma"),
                ("2024-01-07", "NFLX", "epsilon"),
            ]
            for date_str, inst, expected_src in specific_checks:
                if date_str in opt_result:
                    actual_src = opt_result[date_str].mapping.get(inst)
                    if actual_src != expected_src:
                        failures.append(
                            f"CHECK 6f ({date_str}, {inst}): expected "
                            f"'{expected_src}', got '{actual_src}'"
                        )

    # -------------------------------------------------------------------
    # Report
    # -------------------------------------------------------------------
    if failures:
        print("VALIDATION FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
