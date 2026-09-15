
import subprocess
import json
import shutil
import pytest


_scenario_cache: dict = {}


def run_command(cmd, cwd="/app", timeout=60):
    """Run a shell command and return the result."""
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


@pytest.fixture(scope="session", autouse=True)
def setup_environment():
    """Copy test harness to /app so imports resolve correctly."""
    shutil.copy("/tests/test_scenarios.ts", "/app/test_scenarios.ts")


def run_scenario(name, timeout=30):
    """Run a test scenario and return parsed JSON output. Results are cached."""
    if name in _scenario_cache:
        return _scenario_cache[name]

    result = run_command(f"npx tsx test_scenarios.ts {name}", timeout=timeout)
    if result.returncode != 0:
        pytest.fail(
            f"Scenario '{name}' exited with code {result.returncode}.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    try:
        output = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        pytest.fail(
            f"Could not parse JSON from scenario '{name}'.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    _scenario_cache[name] = output
    return output


class TestTypeScriptCompilation:
    """Verify TypeScript compilation succeeds."""

    def test_tsc_no_emit(self):
        result = run_command("npx tsc --noEmit")
        assert result.returncode == 0, (
            f"TypeScript compilation failed:\n{result.stdout}\n{result.stderr}"
        )


class TestAllBookingsSucceed:
    """When all three bookings succeed with requireAll=true."""

    def test_overall_status_completed(self):
        output = run_scenario("all_succeed_require_all")
        assert output["overallStatus"] == "completed", (
            f"Expected 'completed', got '{output['overallStatus']}'"
        )

    def test_total_price(self):
        output = run_scenario("all_succeed_require_all")
        assert output["totalPrice"] == 950, (
            f"Expected totalPrice 950, got {output['totalPrice']}"
        )

    def test_all_bookings_confirmed(self):
        output = run_scenario("all_succeed_require_all")
        assert output["bookings"]["flight"]["status"] == "confirmed"
        assert output["bookings"]["hotel"]["status"] == "confirmed"
        assert output["bookings"]["carRental"]["status"] == "confirmed"

    def test_no_compensation(self):
        output = run_scenario("all_succeed_require_all")
        assert output["compensationLog"] == []


class TestFlightFailsRequireAll:
    """When flight fails but hotel and car succeed, with requireAll=true."""

    def test_overall_status_compensated(self):
        output = run_scenario("flight_fails_require_all")
        assert output["overallStatus"] == "compensated", (
            f"Expected 'compensated', got '{output['overallStatus']}'"
        )

    def test_total_price_zero(self):
        output = run_scenario("flight_fails_require_all")
        assert output["totalPrice"] == 0

    def test_no_flight_cancellation(self):
        """Failed bookings should NOT be cancelled."""
        output = run_scenario("flight_fails_require_all")
        flight_entries = [
            e for e in output["compensationLog"] if "flight" in e.lower()
        ]
        assert len(flight_entries) == 0, (
            f"Should not cancel a failed flight. Log: {output['compensationLog']}"
        )

    def test_hotel_and_car_cancelled(self):
        output = run_scenario("flight_fails_require_all")
        assert len(output["compensationLog"]) == 2, (
            f"Expected 2 compensation entries, got {len(output['compensationLog'])}: "
            f"{output['compensationLog']}"
        )

    def test_correct_cancellation_ids(self):
        """Each cancellation must reference the correct confirmationId."""
        output = run_scenario("flight_fails_require_all")
        log = output["compensationLog"]
        has_hotel = any("HT-CONF" in entry for entry in log)
        has_car = any("CR-CONF" in entry for entry in log)
        assert has_hotel, f"Expected hotel cancellation with HT-CONF. Log: {log}"
        assert has_car, f"Expected car rental cancellation with CR-CONF. Log: {log}"

    def test_compensation_order_by_price(self):
        """Hotel (300) should be compensated before car (150) - highest price first."""
        output = run_scenario("flight_fails_require_all")
        log = output["compensationLog"]
        hotel_idx = next(i for i, e in enumerate(log) if "hotel" in e.lower())
        car_idx = next(i for i, e in enumerate(log) if "car" in e.lower())
        assert hotel_idx < car_idx, (
            f"Expected hotel (price 300) before car (price 150). Log: {log}"
        )


class TestAllBookingsFail:
    """When all three bookings fail."""

    def test_overall_status_failed(self):
        output = run_scenario("all_fail")
        assert output["overallStatus"] == "failed", (
            f"Expected 'failed', got '{output['overallStatus']}'"
        )

    def test_total_price_zero(self):
        output = run_scenario("all_fail")
        assert output["totalPrice"] == 0

    def test_no_compensation(self):
        output = run_scenario("all_fail")
        assert output["compensationLog"] == [], (
            f"No compensation should happen when all fail. Got: {output['compensationLog']}"
        )


class TestFlightFailsNotRequireAll:
    """When flight fails but hotel and car succeed, with requireAll=false."""

    def test_overall_status_partially_completed(self):
        output = run_scenario("flight_fails_not_require_all")
        assert output["overallStatus"] == "partially_completed", (
            f"Expected 'partially_completed', got '{output['overallStatus']}'"
        )

    def test_total_price_only_confirmed(self):
        """totalPrice should sum only confirmed booking prices."""
        output = run_scenario("flight_fails_not_require_all")
        assert output["totalPrice"] == 450, (
            f"Expected totalPrice 450 (hotel 300 + car 150), got {output['totalPrice']}"
        )

    def test_no_compensation(self):
        output = run_scenario("flight_fails_not_require_all")
        assert output["compensationLog"] == []

    def test_flight_marked_failed(self):
        output = run_scenario("flight_fails_not_require_all")
        assert output["bookings"]["flight"]["status"] == "failed"

    def test_hotel_and_car_confirmed(self):
        output = run_scenario("flight_fails_not_require_all")
        assert output["bookings"]["hotel"]["status"] == "confirmed"
        assert output["bookings"]["carRental"]["status"] == "confirmed"


class TestSnapshotPersistence:
    """Machine state can be persisted and restored."""

    def test_restored_actor_completes(self):
        output = run_scenario("snapshot_persistence")
        assert output["overallStatus"] == "completed"
        assert output["totalPrice"] == 950


class TestHotelFailsCarSucceeds:
    """When hotel fails but flight and car succeed, with requireAll=true."""

    def test_overall_status_compensated(self):
        output = run_scenario("hotel_fails_car_succeeds_require_all")
        assert output["overallStatus"] == "compensated"

    def test_compensates_only_confirmed(self):
        """Should cancel flight and car (confirmed), skip hotel (failed)."""
        output = run_scenario("hotel_fails_car_succeeds_require_all")
        log = output["compensationLog"]
        hotel_entries = [e for e in log if "hotel" in e.lower()]
        assert len(hotel_entries) == 0, (
            f"Should not cancel failed hotel. Log: {log}"
        )
        assert len(log) == 2, f"Expected 2 cancellations, got {len(log)}: {log}"

    def test_compensation_order_by_price(self):
        """Flight (500) should be compensated before car (150) - highest price first."""
        output = run_scenario("hotel_fails_car_succeeds_require_all")
        log = output["compensationLog"]
        flight_idx = next(i for i, e in enumerate(log) if "flight" in e.lower())
        car_idx = next(i for i, e in enumerate(log) if "car" in e.lower())
        assert flight_idx < car_idx, (
            f"Expected flight (price 500) before car (price 150). Log: {log}"
        )


class TestFlightRetrySucceeds:
    """When flight fails once then succeeds on retry."""

    def test_overall_status_completed(self):
        output = run_scenario("flight_retries_succeed")
        assert output["overallStatus"] == "completed", (
            f"Expected 'completed', got '{output['overallStatus']}'"
        )

    def test_total_price(self):
        output = run_scenario("flight_retries_succeed")
        assert output["totalPrice"] == 950

    def test_all_bookings_confirmed(self):
        output = run_scenario("flight_retries_succeed")
        assert output["bookings"]["flight"]["status"] == "confirmed"
        assert output["bookings"]["hotel"]["status"] == "confirmed"
        assert output["bookings"]["carRental"]["status"] == "confirmed"


class TestFlightRetryExhausted:
    """When flight retries are exhausted and booking ultimately fails."""

    def test_overall_status_compensated(self):
        output = run_scenario("flight_retries_exhausted")
        assert output["overallStatus"] == "compensated", (
            f"Expected 'compensated', got '{output['overallStatus']}'"
        )

    def test_flight_failed(self):
        output = run_scenario("flight_retries_exhausted")
        assert output["bookings"]["flight"]["status"] == "failed"

    def test_hotel_and_car_compensated_in_order(self):
        """Hotel (300) then car (150) - highest price first."""
        output = run_scenario("flight_retries_exhausted")
        log = output["compensationLog"]
        assert len(log) == 2, f"Expected 2 entries, got {len(log)}: {log}"
        assert "hotel" in log[0].lower(), f"Expected hotel first. Log: {log}"
        assert "car" in log[1].lower(), f"Expected car second. Log: {log}"


class TestCompensationOrdering:
    """Verify compensation order follows confirmed booking price descending."""

    def test_car_expensive_status(self):
        """With car at 600, flight at 500, hotel failed: compensated."""
        output = run_scenario("car_expensive_compensation_order")
        assert output["overallStatus"] == "compensated"

    def test_car_expensive_order(self):
        """Car (600) should be compensated before flight (500)."""
        output = run_scenario("car_expensive_compensation_order")
        log = output["compensationLog"]
        assert len(log) == 2, f"Expected 2 entries, got {len(log)}: {log}"
        assert "car" in log[0].lower(), (
            f"Expected car rental first (price 600). Log: {log}"
        )
        assert "flight" in log[1].lower(), (
            f"Expected flight second (price 500). Log: {log}"
        )
