"""
Test suite for geodetic pipeline debugging task.

"""

import subprocess
import json
import os
import re


class TestTransformsFix:
    """Verify all geodetic transformation pipelines are correctly fixed."""

    def test_gie_passes(self):
        """Run gie on the fixed transforms.gie and verify zero failures."""
        result = subprocess.run(
            ["gie", "/app/transforms.gie"],
            capture_output=True, text=True, timeout=60
        )
        combined = result.stdout + result.stderr
        match = re.search(r"(\d+)\s+tests?\s+FAILED", combined)
        if match:
            failed_count = int(match.group(1))
            assert failed_count == 0, (
                f"gie reported {failed_count} test failures:\n{combined}"
            )
        assert result.returncode == 0, (
            f"gie exited with code {result.returncode}:\n{combined}"
        )

    def test_transforms_has_correct_projections(self):
        """Verify the fixed file contains the correct projection types."""
        with open("/app/transforms.gie") as f:
            content = f.read()

        assert "+proj=sterea" in content, (
            "Missing +proj=sterea (oblique stereographic)"
        )
        assert "+proj=poly" in content, "Missing +proj=poly (polyconic)"
        assert "+proj=aea" in content, "Missing +proj=aea (Albers equal area)"
        assert "+proj=omerc" in content, (
            "Missing +proj=omerc (oblique mercator)"
        )
        assert "+proj=geocent" in content, "Missing +proj=geocent (geocentric)"

    def test_broken_params_removed(self):
        """Verify the broken parameter values are no longer present."""
        with open("/app/transforms.gie") as f:
            content = f.read()

        assert not re.search(r"\+proj=stere\s", content), (
            "Still contains +proj=stere (should be +proj=sterea)"
        )
        assert "+ellps=intl" not in content, (
            "Still contains +ellps=intl (should be +ellps=GRS80)"
        )
        assert "+lon_0=134" not in content, (
            "Still contains +lon_0=134 (should be +lon_0=132)"
        )
        assert "+ellps=clrk66" not in content, (
            "Still contains +ellps=clrk66 (should be +ellps=WGS84)"
        )

    def test_omerc_has_no_uoff(self):
        """Verify the omerc definition includes the +no_uoff flag."""
        with open("/app/transforms.gie") as f:
            content = f.read()
        assert "+no_uoff" in content, (
            "Missing +no_uoff in omerc definition"
        )

    def test_correct_params_present(self):
        """Verify the correct parameter values are present after fixes."""
        with open("/app/transforms.gie") as f:
            content = f.read()

        assert "+lon_0=132" in content, "Missing correct +lon_0=132 for Albers"
        assert "+ellps=GRS80" in content, "Missing +ellps=GRS80"
        assert "+ellps=WGS84" in content, "Missing +ellps=WGS84 for geocentric"

    def test_test_vectors_preserved(self):
        """Verify the file still has all original test vectors."""
        with open("/app/transforms.gie") as f:
            content = f.read()

        accept_count = len(re.findall(r"^accept\s", content, re.MULTILINE))
        expect_count = len(re.findall(r"^expect\s", content, re.MULTILINE))
        assert accept_count >= 30, (
            f"Expected >= 30 accept lines, found {accept_count}"
        )
        assert expect_count >= 30, (
            f"Expected >= 30 expect lines, found {expect_count}"
        )


class TestDiagnosticReport:
    """Verify the diagnostic report is correct."""

    def test_report_exists(self):
        """Verify diagnostic_report.json exists."""
        assert os.path.exists("/app/diagnostic_report.json"), (
            "Missing /app/diagnostic_report.json"
        )

    def test_report_structure(self):
        """Verify report has correct structure with 5 pipeline entries."""
        with open("/app/diagnostic_report.json") as f:
            report = json.load(f)

        assert "pipelines" in report, "Report missing 'pipelines' key"
        pipelines = report["pipelines"]
        assert len(pipelines) == 5, (
            f"Expected 5 pipeline entries, found {len(pipelines)}"
        )

        for entry in pipelines:
            pid = entry.get("pipeline_id", entry.get("id"))
            assert pid is not None, "Entry missing pipeline_id/id"
            assert "projection_type" in entry, (
                f"Pipeline {pid} missing projection_type"
            )
            assert "error_description" in entry, (
                f"Pipeline {pid} missing error_description"
            )
            assert "fix_description" in entry, (
                f"Pipeline {pid} missing fix_description"
            )

    def test_projection_types(self):
        """Verify correct projection types are identified for each pipeline."""
        with open("/app/diagnostic_report.json") as f:
            report = json.load(f)

        type_map = {}
        for entry in report["pipelines"]:
            pid = int(entry.get("pipeline_id", entry.get("id")))
            type_map[pid] = entry["projection_type"].lower()

        assert any(
            k in type_map.get(1, "") for k in ["sterea", "stereographic"]
        ), f"Pipeline 1 type wrong: {type_map.get(1)}"
        assert any(
            k in type_map.get(2, "") for k in ["poly", "polyconic"]
        ), f"Pipeline 2 type wrong: {type_map.get(2)}"
        assert any(
            k in type_map.get(3, "") for k in ["aea", "albers"]
        ), f"Pipeline 3 type wrong: {type_map.get(3)}"
        assert any(
            k in type_map.get(4, "")
            for k in ["omerc", "mercator", "hotine"]
        ), f"Pipeline 4 type wrong: {type_map.get(4)}"
        assert any(
            k in type_map.get(5, "") for k in ["geocent", "geocentric"]
        ), f"Pipeline 5 type wrong: {type_map.get(5)}"

    def test_report_has_task_instance_id(self):
        """Verify the report contains the correct task_instance_id."""
        with open("/app/calibration_data.json") as f:
            cal_data = json.load(f)
        with open("/app/diagnostic_report.json") as f:
            report = json.load(f)
        assert report.get("task_instance_id") == cal_data["task_instance_id"], (
            "task_instance_id mismatch in diagnostic_report.json"
        )


class TestRoundtripValidation:
    """Verify the roundtrip validation GIE file."""

    def test_roundtrip_file_exists(self):
        """Verify roundtrip_validation.gie exists."""
        assert os.path.exists("/app/roundtrip_validation.gie"), (
            "Missing /app/roundtrip_validation.gie"
        )

    def test_roundtrip_gie_passes(self):
        """Run gie on the roundtrip file and verify zero failures."""
        result = subprocess.run(
            ["gie", "/app/roundtrip_validation.gie"],
            capture_output=True, text=True, timeout=120
        )
        combined = result.stdout + result.stderr
        match = re.search(r"(\d+)\s+tests?\s+FAILED", combined)
        if match:
            failed_count = int(match.group(1))
            assert failed_count == 0, (
                f"Roundtrip gie reported {failed_count} failures:\n{combined}"
            )
        assert result.returncode == 0, (
            f"Roundtrip gie exited with code {result.returncode}:\n{combined}"
        )

    def test_roundtrip_has_all_pipelines(self):
        """Verify roundtrip file covers all 5 transformations."""
        with open("/app/roundtrip_validation.gie") as f:
            content = f.read()

        op_count = len(re.findall(r"^operation\s", content, re.MULTILINE))
        assert op_count >= 5, (
            f"Expected >= 5 operations, found {op_count}"
        )

        rt_count = len(re.findall(r"^roundtrip\s", content, re.MULTILINE))
        assert rt_count >= 5, (
            f"Expected >= 5 roundtrip tests, found {rt_count}"
        )

    def test_roundtrip_has_correct_projections(self):
        """Verify roundtrip file uses the correct (fixed) projections."""
        with open("/app/roundtrip_validation.gie") as f:
            content = f.read()

        assert "+proj=sterea" in content, (
            "Roundtrip missing sterea projection"
        )
        assert "+proj=poly" in content, (
            "Roundtrip missing poly projection"
        )
        assert "+proj=aea" in content, (
            "Roundtrip missing aea projection"
        )
        assert "+proj=omerc" in content, (
            "Roundtrip missing omerc projection"
        )
        assert "+proj=geocent" in content, (
            "Roundtrip missing geocent conversion"
        )


class TestCalibration:
    """Verify calibration results via independent PROJ computation."""

    # Correct projection parameters for cs2cs (forward: longlat -> projected)
    PROJ_ARGS = {
        1: [
            "+proj=longlat", "+ellps=bessel", "+to",
            "+proj=sterea", "+lat_0=52.15616055555556",
            "+lon_0=5.38763888888889", "+k_0=0.9999079",
            "+x_0=155000", "+y_0=463000", "+ellps=bessel",
        ],
        2: [
            "+proj=longlat", "+ellps=GRS80", "+to",
            "+proj=poly", "+lat_0=0", "+lon_0=-54",
            "+x_0=5000000", "+y_0=10000000", "+ellps=GRS80",
        ],
        3: [
            "+proj=longlat", "+ellps=GRS80", "+to",
            "+proj=aea", "+lat_0=0", "+lon_0=132",
            "+lat_1=-18", "+lat_2=-36",
            "+x_0=0", "+y_0=0", "+ellps=GRS80",
        ],
        4: [
            "+proj=longlat", "+ellps=GRS80", "+to",
            "+proj=omerc", "+no_uoff", "+lat_0=4", "+lonc=115",
            "+alpha=53.31580995", "+gamma=53.1301023611111",
            "+k_0=0.99984", "+x_0=0", "+y_0=0", "+ellps=GRS80",
        ],
        5: [
            "+proj=longlat", "+ellps=WGS84", "+to",
            "+proj=geocent", "+ellps=WGS84",
        ],
    }

    def _run_cs2cs(self, proj_id, lon, lat, height=0):
        """Run cs2cs independently and return output coordinates."""
        inp = f"{lon} {lat} {height}\n"
        result = subprocess.run(
            ["cs2cs", "-f", "%.6f"] + self.PROJ_ARGS[proj_id],
            input=inp, capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, (
            f"cs2cs failed for projection {proj_id}: {result.stderr}"
        )
        parts = result.stdout.strip().split()
        return [float(x) for x in parts[:3]]

    def test_calibration_file_exists(self):
        """Verify calibration_results.json exists."""
        assert os.path.exists("/app/calibration_results.json"), (
            "Missing /app/calibration_results.json"
        )

    def test_task_instance_id_matches(self):
        """Verify task_instance_id propagated correctly."""
        with open("/app/calibration_data.json") as f:
            cal_data = json.load(f)
        with open("/app/calibration_results.json") as f:
            cal_results = json.load(f)
        assert cal_results.get("task_instance_id") == cal_data["task_instance_id"], (
            "task_instance_id mismatch between calibration_data and "
            "calibration_results"
        )

    def test_calibration_has_all_projections(self):
        """Verify results cover all 5 projections."""
        with open("/app/calibration_results.json") as f:
            cal_results = json.load(f)
        pids = {int(r["projection_id"]) for r in cal_results["results"]}
        assert pids == {1, 2, 3, 4, 5}, (
            f"Expected projection_ids {{1,2,3,4,5}}, got {pids}"
        )

    def test_calibration_results_accuracy(self):
        """Independently compute transforms and compare with agent results."""
        with open("/app/calibration_data.json") as f:
            cal_data = json.load(f)
        with open("/app/calibration_results.json") as f:
            cal_results = json.load(f)

        results_map = {}
        for r in cal_results["results"]:
            results_map[int(r["projection_id"])] = r

        tolerance = 0.05  # meters

        for coord in cal_data["coordinates"]:
            pid = coord["projection_id"]
            lon = coord["longitude"]
            lat = coord["latitude"]
            height = coord.get("height", 0)

            assert pid in results_map, f"Missing result for projection {pid}"
            result = results_map[pid]

            expected = self._run_cs2cs(pid, lon, lat, height)

            if pid <= 4:
                agent_e = float(result["easting"])
                agent_n = float(result["northing"])
                assert abs(agent_e - expected[0]) < tolerance, (
                    f"Projection {pid} easting: agent={agent_e}, "
                    f"expected={expected[0]}, "
                    f"diff={abs(agent_e - expected[0])}"
                )
                assert abs(agent_n - expected[1]) < tolerance, (
                    f"Projection {pid} northing: agent={agent_n}, "
                    f"expected={expected[1]}, "
                    f"diff={abs(agent_n - expected[1])}"
                )
            else:
                agent_x = float(result["x"])
                agent_y = float(result["y"])
                agent_z = float(result["z"])
                assert abs(agent_x - expected[0]) < tolerance, (
                    f"Projection {pid} X: agent={agent_x}, "
                    f"expected={expected[0]}"
                )
                assert abs(agent_y - expected[1]) < tolerance, (
                    f"Projection {pid} Y: agent={agent_y}, "
                    f"expected={expected[1]}"
                )
                assert abs(agent_z - expected[2]) < tolerance, (
                    f"Projection {pid} Z: agent={agent_z}, "
                    f"expected={expected[2]}"
                )
