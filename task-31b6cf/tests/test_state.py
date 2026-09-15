
import json
import os
import pytest


def load_memory_map():
    with open("/app/memory_map.json") as f:
        return json.load(f)


def load_mpu_config():
    with open("/app/mpu_config.json") as f:
        return json.load(f)


def is_power_of_2(n):
    return n > 0 and (n & (n - 1)) == 0


def get_enabled_ranges(region):
    """Return list of (start, end) tuples for enabled subregions."""
    base = region["base_address"]
    size = region["region_size"]
    srd = region["subregion_disable"]
    subregion_size = size // 8
    ranges = []
    for i in range(8):
        if not (srd & (1 << i)):
            sr_start = base + i * subregion_size
            sr_end = sr_start + subregion_size
            ranges.append((sr_start, sr_end))
    return ranges


def ranges_overlap(r1_start, r1_end, r2_start, r2_end):
    return r1_start < r2_end and r2_start < r1_end


class TestMPUConfigExists:
    def test_output_exists(self):
        assert os.path.exists("/app/mpu_config.json"), \
            "Output file /app/mpu_config.json does not exist"

    def test_output_valid_json(self):
        with open("/app/mpu_config.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)


class TestMPURegionValidity:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.memory_map = load_memory_map()
        self.config = load_mpu_config()

    def test_all_processes_have_config(self):
        process_names = {p["name"] for p in self.memory_map["processes"]}
        config_names = set(self.config.keys())
        assert process_names == config_names, \
            f"Expected processes {process_names}, got {config_names}"

    def test_region_power_of_2_size(self):
        for proc_name, proc_config in self.config.items():
            for i, region in enumerate(proc_config["regions"]):
                size = region["region_size"]
                assert is_power_of_2(size), \
                    f"{proc_name} region {i}: size {size} ({hex(size)}) not power of 2"

    def test_region_alignment(self):
        for proc_name, proc_config in self.config.items():
            for i, region in enumerate(proc_config["regions"]):
                base = region["base_address"]
                size = region["region_size"]
                assert base % size == 0, \
                    f"{proc_name} region {i}: base {hex(base)} not aligned to size {hex(size)}"

    def test_region_min_size(self):
        min_size = self.memory_map["system"]["min_region_size"]
        for proc_name, proc_config in self.config.items():
            for i, region in enumerate(proc_config["regions"]):
                assert region["region_size"] >= min_size, \
                    f"{proc_name} region {i}: size {region['region_size']} < {min_size}"

    def test_srd_valid_range(self):
        for proc_name, proc_config in self.config.items():
            for i, region in enumerate(proc_config["regions"]):
                srd = region["subregion_disable"]
                assert isinstance(srd, int) and 0 <= srd <= 255, \
                    f"{proc_name} region {i}: SRD {srd} not in [0, 255]"

    def test_region_count_limit(self):
        max_regions = self.memory_map["system"]["mpu_regions_per_process"]
        for proc_name, proc_config in self.config.items():
            n = len(proc_config["regions"])
            assert n <= max_regions, \
                f"{proc_name}: {n} regions exceeds limit of {max_regions}"

    def test_no_fully_disabled_regions(self):
        for proc_name, proc_config in self.config.items():
            for i, region in enumerate(proc_config["regions"]):
                assert region["subregion_disable"] != 0xFF, \
                    f"{proc_name} region {i}: all subregions disabled (useless region)"

    def test_at_least_two_regions_per_process(self):
        for proc_name, proc_config in self.config.items():
            assert len(proc_config["regions"]) >= 2, \
                f"{proc_name}: needs at least 2 regions (flash + RAM), has {len(proc_config['regions'])}"


class TestMPUCoverage:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.memory_map = load_memory_map()
        self.config = load_mpu_config()

    def _check_coverage(self, proc_name, mem_start, mem_size, mem_type):
        """Verify every byte in [mem_start, mem_start+mem_size) is covered."""
        mem_end = mem_start + mem_size

        enabled = []
        for region in self.config[proc_name]["regions"]:
            enabled.extend(get_enabled_ranges(region))

        # Collect all boundary points within the memory range
        boundaries = sorted(set(
            [mem_start, mem_end] +
            [s for s, e in enabled if mem_start <= s <= mem_end] +
            [e for s, e in enabled if mem_start <= e <= mem_end]
        ))

        for i in range(len(boundaries) - 1):
            seg_start = boundaries[i]
            seg_end = boundaries[i + 1]
            if seg_start >= mem_end or seg_end <= mem_start:
                continue
            covered = any(s <= seg_start and seg_end <= e for s, e in enabled)
            assert covered, \
                f"{proc_name}: {mem_type} range [{hex(seg_start)}, {hex(seg_end)}) not covered by any enabled subregion"

    def test_sensor_flash_coverage(self):
        proc = next(p for p in self.memory_map["processes"] if p["name"] == "sensor")
        self._check_coverage("sensor", proc["flash"]["start"], proc["flash"]["size"], "flash")

    def test_sensor_ram_coverage(self):
        proc = next(p for p in self.memory_map["processes"] if p["name"] == "sensor")
        self._check_coverage("sensor", proc["ram"]["start"], proc["ram"]["size"], "RAM")

    def test_network_flash_coverage(self):
        proc = next(p for p in self.memory_map["processes"] if p["name"] == "network")
        self._check_coverage("network", proc["flash"]["start"], proc["flash"]["size"], "flash")

    def test_network_ram_coverage(self):
        proc = next(p for p in self.memory_map["processes"] if p["name"] == "network")
        self._check_coverage("network", proc["ram"]["start"], proc["ram"]["size"], "RAM")

    def test_crypto_flash_coverage(self):
        proc = next(p for p in self.memory_map["processes"] if p["name"] == "crypto")
        self._check_coverage("crypto", proc["flash"]["start"], proc["flash"]["size"], "flash")

    def test_crypto_ram_coverage(self):
        proc = next(p for p in self.memory_map["processes"] if p["name"] == "crypto")
        self._check_coverage("crypto", proc["ram"]["start"], proc["ram"]["size"], "RAM")

    def test_display_flash_coverage(self):
        proc = next(p for p in self.memory_map["processes"] if p["name"] == "display")
        self._check_coverage("display", proc["flash"]["start"], proc["flash"]["size"], "flash")

    def test_display_ram_coverage(self):
        proc = next(p for p in self.memory_map["processes"] if p["name"] == "display")
        self._check_coverage("display", proc["ram"]["start"], proc["ram"]["size"], "RAM")


class TestMPUIsolation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.memory_map = load_memory_map()
        self.config = load_mpu_config()

    def test_kernel_flash_isolation(self):
        """No process's enabled regions overlap kernel flash."""
        k_start = self.memory_map["kernel"]["flash"]["start"]
        k_end = k_start + self.memory_map["kernel"]["flash"]["size"]

        for proc_name, proc_config in self.config.items():
            for region in proc_config["regions"]:
                for sr_start, sr_end in get_enabled_ranges(region):
                    assert not ranges_overlap(sr_start, sr_end, k_start, k_end), \
                        f"{proc_name}: enabled [{hex(sr_start)}, {hex(sr_end)}) overlaps kernel flash [{hex(k_start)}, {hex(k_end)})"

    def test_kernel_ram_isolation(self):
        """No process's enabled regions overlap kernel RAM."""
        k_start = self.memory_map["kernel"]["ram"]["start"]
        k_end = k_start + self.memory_map["kernel"]["ram"]["size"]

        for proc_name, proc_config in self.config.items():
            for region in proc_config["regions"]:
                for sr_start, sr_end in get_enabled_ranges(region):
                    assert not ranges_overlap(sr_start, sr_end, k_start, k_end), \
                        f"{proc_name}: enabled [{hex(sr_start)}, {hex(sr_end)}) overlaps kernel RAM [{hex(k_start)}, {hex(k_end)})"

    def test_cross_process_flash_isolation(self):
        """No process's enabled regions overlap another process's flash."""
        processes = self.memory_map["processes"]

        for proc_a in processes:
            name_a = proc_a["name"]
            enabled_a = []
            for region in self.config[name_a]["regions"]:
                enabled_a.extend(get_enabled_ranges(region))

            for proc_b in processes:
                if proc_a["name"] == proc_b["name"]:
                    continue
                b_start = proc_b["flash"]["start"]
                b_end = b_start + proc_b["flash"]["size"]

                for sr_start, sr_end in enabled_a:
                    assert not ranges_overlap(sr_start, sr_end, b_start, b_end), \
                        f"{name_a}: enabled [{hex(sr_start)}, {hex(sr_end)}) overlaps {proc_b['name']}'s flash [{hex(b_start)}, {hex(b_end)})"

    def test_cross_process_ram_isolation(self):
        """No process's enabled regions overlap another process's RAM."""
        processes = self.memory_map["processes"]

        for proc_a in processes:
            name_a = proc_a["name"]
            enabled_a = []
            for region in self.config[name_a]["regions"]:
                enabled_a.extend(get_enabled_ranges(region))

            for proc_b in processes:
                if proc_a["name"] == proc_b["name"]:
                    continue
                b_start = proc_b["ram"]["start"]
                b_end = b_start + proc_b["ram"]["size"]

                for sr_start, sr_end in enabled_a:
                    assert not ranges_overlap(sr_start, sr_end, b_start, b_end), \
                        f"{name_a}: enabled [{hex(sr_start)}, {hex(sr_end)}) overlaps {proc_b['name']}'s RAM [{hex(b_start)}, {hex(b_end)})"


class TestMPUEfficiency:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.memory_map = load_memory_map()
        self.config = load_mpu_config()

    def test_waste_bounded(self):
        """Over-granted memory must not exceed 100% of total allocated."""
        total_allocated = 0
        total_granted = 0

        for proc in self.memory_map["processes"]:
            total_allocated += proc["flash"]["size"] + proc["ram"]["size"]

        for proc_name, proc_config in self.config.items():
            for region in proc_config["regions"]:
                for sr_start, sr_end in get_enabled_ranges(region):
                    total_granted += sr_end - sr_start

        waste = total_granted - total_allocated
        assert waste >= 0, "Granted memory less than allocated (impossible if coverage passes)"
        assert waste <= total_allocated, \
            f"Waste {waste} bytes ({waste * 100 // total_allocated}%) exceeds 100% of allocated {total_allocated} bytes"

    def test_no_excessively_large_regions(self):
        """No single region should be more than 16x the process's total allocation."""
        proc_map = {p["name"]: p for p in self.memory_map["processes"]}
        for proc_name, proc_config in self.config.items():
            proc = proc_map[proc_name]
            total_alloc = proc["flash"]["size"] + proc["ram"]["size"]
            for i, region in enumerate(proc_config["regions"]):
                assert region["region_size"] <= total_alloc * 16, \
                    f"{proc_name} region {i}: size {hex(region['region_size'])} is excessively large relative to allocation {hex(total_alloc)}"
