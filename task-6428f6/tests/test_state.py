
import json
import math
import os
import sqlite3
import pytest
from collections import defaultdict

DATA_DIR = "/app/data"
OUTPUT_DIR = "/app/output"
GPKG_PATH = os.path.join(DATA_DIR, "hydrofabric.gpkg")


def _load_from_gpkg():
    """Load catchment and nexus data from the GeoPackage database."""
    conn = sqlite3.connect(GPKG_PATH)

    # Discover catchment columns robustly
    cat_info = conn.execute("PRAGMA table_info(catchments)").fetchall()
    cat_cols = [row[1] for row in cat_info]

    id_col = next((c for c in cat_cols if c.lower() == "id"), None)
    if id_col is None:
        id_col = next(
            (c for c in cat_cols if "id" in c.lower() and c.lower() not in ("fid", "toid")),
            None,
        )
    area_col = next(c for c in cat_cols if "area" in c.lower())
    toid_col = next(c for c in cat_cols if c.lower() == "toid")

    catchments = {}
    for row in conn.execute(
        f"SELECT [{id_col}], [{area_col}], [{toid_col}] FROM catchments"
    ):
        catchments[row[0]] = {"area": row[1], "toid": row[2]}

    # Discover nexus columns
    nex_info = conn.execute("PRAGMA table_info(nexuses)").fetchall()
    nex_cols = [row[1] for row in nex_info]

    nex_id_col = next((c for c in nex_cols if c.lower() == "id"), None)
    if nex_id_col is None:
        nex_id_col = next(
            (c for c in nex_cols if "id" in c.lower() and c.lower() not in ("fid", "toid")),
            None,
        )
    nex_toid_col = next(c for c in nex_cols if c.lower() == "toid")

    nexuses = {}
    for row in conn.execute(
        f"SELECT [{nex_id_col}], [{nex_toid_col}] FROM nexuses"
    ):
        nexuses[row[0]] = {"toid": row[1]}

    conn.close()
    return catchments, nexuses


def _build_graph(catchments, nexuses):
    """Build adjacency structures for the drainage network."""
    nex_sources = defaultdict(list)
    for cid, c in catchments.items():
        nex_sources[c["toid"]].append(cid)

    upstream_cats = defaultdict(set)
    for nid, n in nexuses.items():
        ds = n["toid"]
        if ds in catchments:
            for src in nex_sources[nid]:
                upstream_cats[ds].add(src)

    return dict(nex_sources), dict(upstream_cats)


def _compute_expected():
    """Independently compute all expected network metrics."""
    catchments, nexuses = _load_from_gpkg()
    nex_sources, upstream_cats = _build_graph(catchments, nexuses)

    all_cat_ids = set(catchments.keys())
    all_nex_ids = set(nexuses.keys())

    # headwaters
    headwaters = sorted(
        c for c in all_cat_ids if c not in upstream_cats or len(upstream_cats[c]) == 0
    )

    # outlet
    outlet = None
    for nid, n in nexuses.items():
        if n["toid"] not in catchments:
            outlet = nid
            break

    # total area
    total_area = round(sum(c["area"] for c in catchments.values()), 6)

    # Strahler orders
    orders = {}

    def _strahler(cid):
        if cid in orders:
            return orders[cid]
        ups = upstream_cats.get(cid, set())
        if not ups:
            orders[cid] = 1
            return 1
        up_orders = [_strahler(u) for u in ups]
        mx = max(up_orders)
        cnt = sum(1 for o in up_orders if o == mx)
        orders[cid] = mx + 1 if cnt >= 2 else mx
        return orders[cid]

    for cid in all_cat_ids:
        _strahler(cid)
    max_order = max(orders.values())

    # Shreve magnitudes
    magnitudes = {}

    def _shreve(cid):
        if cid in magnitudes:
            return magnitudes[cid]
        ups = upstream_cats.get(cid, set())
        if not ups:
            magnitudes[cid] = 1
            return 1
        magnitudes[cid] = sum(_shreve(u) for u in ups)
        return magnitudes[cid]

    for cid in all_cat_ids:
        _shreve(cid)

    # Horton bifurcation ratio — multiple valid methods
    order_counts = defaultdict(int)
    for o in orders.values():
        order_counts[o] += 1
    sorted_orders = sorted(order_counts.keys())

    ratios = []
    for i in range(len(sorted_orders) - 1):
        n_i = order_counts[sorted_orders[i]]
        n_ip1 = order_counts[sorted_orders[i + 1]]
        ratios.append(n_i / n_ip1)

    rb_arithmetic = sum(ratios) / len(ratios) if ratios else 1.0
    rb_geometric = math.exp(sum(math.log(r) for r in ratios) / len(ratios)) if ratios else 1.0

    # cumulative areas
    cumulative = {}

    def _cum(cid):
        if cid in cumulative:
            return cumulative[cid]
        area = catchments[cid]["area"]
        for u in upstream_cats.get(cid, set()):
            area += _cum(u)
        cumulative[cid] = area
        return area

    for cid in all_cat_ids:
        _cum(cid)

    contributing = {}
    for nid in all_nex_ids:
        srcs = nex_sources.get(nid, [])
        contributing[nid] = round(sum(cumulative[s] for s in srcs), 6)

    # longest path
    path_len = {}
    path_trace = {}

    def _longest(cid):
        if cid in path_len:
            return path_len[cid]
        ups = upstream_cats.get(cid, set())
        if not ups:
            path_len[cid] = 1
            path_trace[cid] = [cid]
            return 1
        best_l, best_u = 0, None
        for u in sorted(ups):
            l = _longest(u)
            if l > best_l:
                best_l = l
                best_u = u
        path_len[cid] = best_l + 1
        path_trace[cid] = path_trace[best_u] + [cid]
        return path_len[cid]

    for cid in all_cat_ids:
        _longest(cid)
    global_max_len = max(path_len.values())

    return {
        "headwaters": headwaters,
        "outlet": outlet,
        "total_area": total_area,
        "orders": orders,
        "max_order": max_order,
        "magnitudes": magnitudes,
        "rb_arithmetic": rb_arithmetic,
        "rb_geometric": rb_geometric,
        "contributing": contributing,
        "longest_length": global_max_len,
        "all_cat_ids": all_cat_ids,
        "all_nex_ids": all_nex_ids,
        "catchments": catchments,
        "nexuses": nexuses,
        "nex_sources": nex_sources,
        "upstream_cats": upstream_cats,
        "path_len": path_len,
    }


@pytest.fixture(scope="module")
def expected():
    return _compute_expected()


@pytest.fixture(scope="module")
def network_result():
    p = os.path.join(OUTPUT_DIR, "network_analysis.json")
    assert os.path.exists(p), f"Missing {p}"
    with open(p) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def partition_result():
    p = os.path.join(OUTPUT_DIR, "partition_config.json")
    assert os.path.exists(p), f"Missing {p}"
    with open(p) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def realization_result():
    p = os.path.join(OUTPUT_DIR, "realization_config.json")
    assert os.path.exists(p), f"Missing {p}"
    with open(p) as f:
        return json.load(f)


# ──────────────────────  network_analysis tests  ──────────────────────


class TestHeadwaters:
    def test_correct_set(self, network_result, expected):
        assert set(network_result["headwater_catchments"]) == set(expected["headwaters"])

    def test_sorted(self, network_result):
        hw = network_result["headwater_catchments"]
        assert hw == sorted(hw), "headwater_catchments must be sorted"


class TestOutlet:
    def test_outlet_nexus(self, network_result, expected):
        assert network_result["outlet_nexus"] == expected["outlet"]


class TestTotalArea:
    def test_total_area(self, network_result, expected):
        assert abs(network_result["total_drainage_area_sqkm"] - expected["total_area"]) < 0.01


class TestStrahlerOrders:
    def test_all_catchments_present(self, network_result, expected):
        result_keys = set(network_result["strahler_orders"].keys())
        assert result_keys == expected["all_cat_ids"]

    def test_order_values(self, network_result, expected):
        for cid, exp_order in expected["orders"].items():
            got = network_result["strahler_orders"].get(cid)
            assert got == exp_order, f"{cid}: expected order {exp_order}, got {got}"

    def test_max_order(self, network_result, expected):
        assert network_result["max_strahler_order"] == expected["max_order"]


class TestShreveMagnitudes:
    def test_all_catchments_present(self, network_result, expected):
        result_keys = set(network_result["shreve_magnitudes"].keys())
        assert result_keys == expected["all_cat_ids"]

    def test_magnitude_values(self, network_result, expected):
        for cid, exp_mag in expected["magnitudes"].items():
            got = network_result["shreve_magnitudes"].get(cid)
            assert got == exp_mag, f"{cid}: expected Shreve magnitude {exp_mag}, got {got}"

    def test_outlet_magnitude_equals_headwater_count(self, network_result, expected):
        """Shreve magnitude at outlet catchment should equal number of headwaters."""
        # Find the most-downstream catchment (one with max Shreve magnitude)
        mags = network_result["shreve_magnitudes"]
        max_mag = max(mags.values())
        assert max_mag == len(expected["headwaters"])


class TestBifurcationRatio:
    def test_reasonable_value(self, network_result, expected):
        rb = network_result["bifurcation_ratio"]
        assert isinstance(rb, (int, float)), "bifurcation_ratio must be numeric"
        # Accept arithmetic mean or geometric mean (both valid methods)
        valid = (
            abs(rb - expected["rb_arithmetic"]) < 0.05
            or abs(rb - expected["rb_geometric"]) < 0.05
        )
        assert valid, (
            f"bifurcation_ratio {rb} not close to arithmetic mean "
            f"({expected['rb_arithmetic']:.4f}) or geometric mean "
            f"({expected['rb_geometric']:.4f})"
        )

    def test_in_range(self, network_result):
        rb = network_result["bifurcation_ratio"]
        assert 1.0 < rb < 6.0, f"Rb={rb} outside typical range [1, 6]"


class TestContributingAreas:
    def test_all_nexuses_present(self, network_result, expected):
        result_keys = set(network_result["contributing_areas"].keys())
        assert result_keys == expected["all_nex_ids"]

    def test_area_values(self, network_result, expected):
        for nid, exp_area in expected["contributing"].items():
            got = network_result["contributing_areas"].get(nid)
            assert got is not None, f"Missing contributing area for {nid}"
            assert abs(got - exp_area) < 0.02, f"{nid}: expected {exp_area}, got {got}"

    def test_outlet_equals_total(self, network_result, expected):
        outlet = expected["outlet"]
        assert abs(
            network_result["contributing_areas"][outlet] - expected["total_area"]
        ) < 0.02


class TestLongestPath:
    def test_length(self, network_result, expected):
        lp = network_result["longest_flow_path"]
        assert lp["length"] == expected["longest_length"]

    def test_path_length_matches(self, network_result):
        lp = network_result["longest_flow_path"]
        assert len(lp["path"]) == lp["length"]

    def test_path_is_valid_drainage(self, network_result, expected):
        """Each consecutive pair must be connected via a nexus."""
        path = network_result["longest_flow_path"]["path"]
        cats = expected["catchments"]
        upstream = expected["upstream_cats"]
        for i in range(len(path) - 1):
            src, dst = path[i], path[i + 1]
            assert src in cats, f"{src} not a valid catchment"
            assert dst in cats, f"{dst} not a valid catchment"
            assert src in upstream.get(dst, set()), (
                f"{src} is not directly upstream of {dst}"
            )

    def test_path_starts_at_headwater(self, network_result, expected):
        path = network_result["longest_flow_path"]["path"]
        assert path[0] in expected["headwaters"]

    def test_path_is_maximal(self, network_result, expected):
        assert network_result["longest_flow_path"]["length"] == expected["longest_length"]


# ──────────────────────  realization_config tests  ──────────────────────


class TestRealizationStructure:
    def test_has_global(self, realization_result):
        assert "global" in realization_result, "Missing 'global' key"

    def test_has_time(self, realization_result):
        assert "time" in realization_result, "Missing 'time' key"

    def test_time_section(self, realization_result):
        t = realization_result["time"]
        assert "start_time" in t, "Missing start_time"
        assert "end_time" in t, "Missing end_time"
        assert "output_interval" in t, "Missing output_interval"
        assert isinstance(t["output_interval"], (int, float))
        assert t["output_interval"] == 3600, "output_interval should be 3600 (hourly)"


class TestRealizationFormulation:
    def test_has_formulations(self, realization_result):
        g = realization_result["global"]
        assert "formulations" in g, "Missing 'formulations'"
        assert len(g["formulations"]) >= 1

    def test_bmi_multi(self, realization_result):
        f = realization_result["global"]["formulations"][0]
        assert f["name"] == "bmi_multi", f"Expected bmi_multi, got {f['name']}"

    def test_has_modules(self, realization_result):
        params = realization_result["global"]["formulations"][0]["params"]
        assert "modules" in params, "Missing 'modules' in bmi_multi params"
        assert len(params["modules"]) >= 2, "Need at least 2 modules (PET + CFE)"


class TestRealizationModuleCoupling:
    def _find_pet_and_cfe_indices(self, realization_result):
        modules = realization_result["global"]["formulations"][0]["params"]["modules"]
        pet_idx = None
        cfe_idx = None
        for i, mod in enumerate(modules):
            p = mod.get("params", {})
            name_lower = p.get("model_type_name", "").lower()
            init = p.get("init_config", "")
            reg = p.get("registration_function", "")
            if "pet" in name_lower or "pet" in init.lower() or "pet" in reg.lower():
                pet_idx = i
            if "cfe" in name_lower or "cfe" in init.lower():
                if "pet" not in name_lower and "pet" not in init.lower():
                    cfe_idx = i
        return pet_idx, cfe_idx

    def test_pet_before_cfe(self, realization_result):
        pet_idx, cfe_idx = self._find_pet_and_cfe_indices(realization_result)
        assert pet_idx is not None, "No PET module found"
        assert cfe_idx is not None, "No CFE module found"
        assert pet_idx < cfe_idx, "PET module must appear before CFE module"

    def test_cfe_init_config(self, realization_result):
        modules = realization_result["global"]["formulations"][0]["params"]["modules"]
        _, cfe_idx = self._find_pet_and_cfe_indices(realization_result)
        cfe_init = modules[cfe_idx]["params"].get("init_config", "")
        assert os.path.basename(cfe_init) == "cfe_bmi_config.txt", (
            f"CFE init_config should reference cfe_bmi_config.txt, got {cfe_init}"
        )

    def test_pet_init_config(self, realization_result):
        modules = realization_result["global"]["formulations"][0]["params"]["modules"]
        pet_idx, _ = self._find_pet_and_cfe_indices(realization_result)
        pet_init = modules[pet_idx]["params"].get("init_config", "")
        assert os.path.basename(pet_init) == "pet_bmi_config.txt", (
            f"PET init_config should reference pet_bmi_config.txt, got {pet_init}"
        )

    def test_cfe_main_output(self, realization_result):
        modules = realization_result["global"]["formulations"][0]["params"]["modules"]
        _, cfe_idx = self._find_pet_and_cfe_indices(realization_result)
        cfe_output = modules[cfe_idx]["params"].get("main_output_variable", "")
        assert cfe_output == "Q_OUT", f"CFE main_output_variable should be Q_OUT, got {cfe_output}"


class TestRealizationForcing:
    def test_has_forcing(self, realization_result):
        g = realization_result["global"]
        assert "forcing" in g, "Missing 'forcing' in global"

    def test_forcing_path(self, realization_result):
        forcing = realization_result["global"]["forcing"]
        assert "path" in forcing, "Missing 'path' in forcing"
        path = forcing["path"]
        assert "forcing" in path, f"Forcing path should reference forcing directory, got {path}"

    def test_forcing_pattern(self, realization_result):
        forcing = realization_result["global"]["forcing"]
        assert "file_pattern" in forcing, "Missing 'file_pattern' in forcing"


# ──────────────────────  partition_config tests  ──────────────────────


class TestPartitionCompleteness:
    def test_num_partitions(self, partition_result):
        assert partition_result["num_partitions"] == 4
        assert len(partition_result["partitions"]) == 4

    def test_all_catchments_assigned(self, partition_result, expected):
        assigned = set()
        for p in partition_result["partitions"]:
            assigned.update(p["catchment_ids"])
        assert assigned == expected["all_cat_ids"]

    def test_all_nexuses_assigned(self, partition_result, expected):
        assigned = set()
        for p in partition_result["partitions"]:
            assigned.update(p["nexus_ids"])
        assert assigned == expected["all_nex_ids"]

    def test_no_duplicate_catchments(self, partition_result):
        seen = []
        for p in partition_result["partitions"]:
            seen.extend(p["catchment_ids"])
        assert len(seen) == len(set(seen)), "Duplicate catchment assignment"

    def test_no_duplicate_nexuses(self, partition_result):
        seen = []
        for p in partition_result["partitions"]:
            seen.extend(p["nexus_ids"])
        assert len(seen) == len(set(seen)), "Duplicate nexus assignment"


class TestPartitionBalance:
    def test_max_catchments_per_partition(self, partition_result):
        for p in partition_result["partitions"]:
            assert len(p["catchment_ids"]) <= 6, (
                f"Partition {p['id']} has {len(p['catchment_ids'])} catchments (max 6)"
            )

    def test_partition_ids(self, partition_result):
        ids = sorted(p["id"] for p in partition_result["partitions"])
        assert ids == [0, 1, 2, 3]


class TestNexusAssignment:
    def test_nexus_in_downstream_partition(self, partition_result, expected):
        """Each nexus must be in the same partition as its downstream catchment."""
        nexuses = expected["nexuses"]
        cats = expected["all_cat_ids"]

        cat_partition = {}
        nex_partition = {}
        for p in partition_result["partitions"]:
            for c in p["catchment_ids"]:
                cat_partition[c] = p["id"]
            for n in p["nexus_ids"]:
                nex_partition[n] = p["id"]

        for nid, n in nexuses.items():
            ds = n["toid"]
            if ds in cats:
                assert nex_partition[nid] == cat_partition[ds], (
                    f"{nid} (partition {nex_partition[nid]}) must be in same "
                    f"partition as its downstream {ds} (partition {cat_partition[ds]})"
                )


class TestRemoteNexuses:
    def test_remote_count(self, partition_result):
        assert len(partition_result["remote_nexuses"]) <= 5

    def test_remote_sorted(self, partition_result):
        rn = partition_result["remote_nexuses"]
        assert rn == sorted(rn), "remote_nexuses must be sorted"

    def test_remote_correctness(self, partition_result, expected):
        """Verify remote nexuses are exactly those with cross-partition sources."""
        nex_sources = expected["nex_sources"]

        cat_partition = {}
        nex_partition = {}
        for p in partition_result["partitions"]:
            for c in p["catchment_ids"]:
                cat_partition[c] = p["id"]
            for n in p["nexus_ids"]:
                nex_partition[n] = p["id"]

        computed_remote = set()
        for nid in expected["all_nex_ids"]:
            np = nex_partition[nid]
            for src in nex_sources.get(nid, []):
                if cat_partition[src] != np:
                    computed_remote.add(nid)
                    break

        assert set(partition_result["remote_nexuses"]) == computed_remote, (
            f"Expected remote nexuses {sorted(computed_remote)}, "
            f"got {partition_result['remote_nexuses']}"
        )
