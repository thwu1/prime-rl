"""
Comprehensive tests for the multi-calendar date conversion engine with
timezone support. Uses Python reference implementations to generate test
vectors and verify the C++ program's output.
"""


import subprocess
import os
import pytest

ENGINE = "/app/build/calendar_engine"

# ================================================================
# Reference implementations (correct algorithms)
# ================================================================

def gregorian_to_days(y, m, d):
    y -= (1 if m <= 2 else 0)
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m - 3 if m > 2 else m + 9) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def gregorian_from_days(z):
    z += 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (y + (1 if m <= 2 else 0), m, d)


def julian_to_days(y, m, d):
    y -= (1 if m <= 2 else 0)
    era = y // 4
    yoe = y - era * 4
    doy = (153 * (m - 3 if m > 2 else m + 9) + 2) // 5 + d - 1
    doe = yoe * 365 + doy
    return era * 1461 + doe - 719470


def julian_from_days(z):
    z += 719470
    era = z // 1461
    doe = z - era * 1461
    yoe = (doe - doe // 1460) // 365
    y = yoe + era * 4
    doy = doe - 365 * yoe
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (y + (1 if m <= 2 else 0), m, d)


def islamic_is_leap(y):
    yy = y - 1
    era = yy // 30
    yoe = yy - era * 30
    return yoe in {1, 4, 6, 9, 12, 15, 17, 20, 23, 25, 28}


def islamic_to_days(y, m, d):
    yy = y - 1
    era = yy // 30
    yoe = yy - era * 30
    doy = 29 * (m - 1) + m // 2 + d - 1
    doe = yoe * 354 + (11 * (yoe + 1) + 3) // 30 + doy
    return era * 10631 + doe - 492148


def islamic_from_days(z):
    z += 492148
    era = z // 10631
    doe = z - era * 10631
    yoe = (30 * doe + 10646) // 10631 - 1
    y = yoe + era * 30 + 1
    doy = doe - (yoe * 354 + (11 * (yoe + 1) + 3) // 30)
    m = (11 * doy + 330) // 325
    d = doy - (29 * (m - 1) + m // 2) + 1
    return (y, m, d)


def weekday_from_days(z):
    """0=Sun, 1=Mon, ..., 6=Sat. z=0 is Thursday (4)."""
    return (z + 4) % 7


def iso_week_from_gregorian(y, m, d):
    serial = gregorian_to_days(y, m, d)
    wd = weekday_from_days(serial)
    iso_wd = 7 if wd == 0 else wd
    thu_serial = serial + (4 - iso_wd)
    thu_y, _, _ = gregorian_from_days(thu_serial)
    iso_year = thu_y
    jan4 = gregorian_to_days(iso_year, 1, 4)
    jan4_wd = weekday_from_days(jan4)
    jan4_iso_wd = 7 if jan4_wd == 0 else jan4_wd
    week1_mon = jan4 - (jan4_iso_wd - 1)
    iso_week = (serial - week1_mon) // 7 + 1
    return (iso_year, iso_week, iso_wd)


def gregorian_from_iso_week(iso_year, iso_week, iso_weekday):
    jan4 = gregorian_to_days(iso_year, 1, 4)
    jan4_wd = weekday_from_days(jan4)
    jan4_iso_wd = 7 if jan4_wd == 0 else jan4_wd
    week1_mon = jan4 - (jan4_iso_wd - 1)
    serial = week1_mon + (iso_week - 1) * 7 + (iso_weekday - 1)
    return gregorian_from_days(serial)


# ================================================================
# Timezone reference implementations
# ================================================================

TZ_RULES = [
    {"zone": "America/New_York", "std": -300, "dst": -240,
     "start": (3, 0, 2, 2), "end": (11, 0, 1, 2)},
    {"zone": "Europe/London", "std": 0, "dst": 60,
     "start": (3, 0, 5, 1), "end": (10, 0, 5, 2)},
    {"zone": "Asia/Tokyo", "std": 540, "dst": 540,
     "start": None, "end": None},
    {"zone": "America/Los_Angeles", "std": -480, "dst": -420,
     "start": (3, 0, 2, 2), "end": (11, 0, 1, 2)},
    {"zone": "Europe/Berlin", "std": 60, "dst": 120,
     "start": (3, 0, 5, 2), "end": (10, 0, 5, 3)},
    {"zone": "Australia/Sydney", "std": 600, "dst": 660,
     "start": (10, 0, 1, 2), "end": (4, 0, 1, 3)},
]


def py_nth_weekday(year, month, dow, n):
    """Find day of month for nth occurrence of dow (0=Sun) in month."""
    if month == 2:
        days = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
    elif month in (4, 6, 9, 11):
        days = 30
    else:
        days = 31

    if n == 5:
        for d in range(days, 0, -1):
            if weekday_from_days(gregorian_to_days(year, month, d)) == dow:
                return d
    else:
        count = 0
        for d in range(1, days + 1):
            if weekday_from_days(gregorian_to_days(year, month, d)) == dow:
                count += 1
                if count == n:
                    return d
    return 1


def py_is_in_dst(rule, y, m, d, h):
    if rule["start"] is None:
        return False
    sm, sdow, sweek, shour = rule["start"]
    em, edow, eweek, ehour = rule["end"]
    start_day = py_nth_weekday(y, sm, sdow, sweek)
    end_day = py_nth_weekday(y, em, edow, eweek)

    local = gregorian_to_days(y, m, d)
    start = gregorian_to_days(y, sm, start_day)
    end = gregorian_to_days(y, em, end_day)

    after_start = (local > start) or (local == start and h >= shour)
    before_end = (local < end) or (local == end and h < ehour)

    if sm < em:
        return after_start and before_end
    else:
        return after_start or before_end


def py_tz_offset(zone, y, m, d, h, min_):
    for rule in TZ_RULES:
        if rule["zone"] == zone:
            return rule["dst"] if py_is_in_dst(rule, y, m, d, h) else rule["std"]
    return 0


def py_to_utc(zone, y, m, d, h, min_):
    offset = py_tz_offset(zone, y, m, d, h, min_)
    total = h * 60 + min_ - offset
    serial = gregorian_to_days(y, m, d)
    while total < 0:
        serial -= 1
        total += 1440
    while total >= 1440:
        serial += 1
        total -= 1440
    uy, um, ud = gregorian_from_days(serial)
    return (uy, um, ud, total // 60, total % 60)


# ================================================================
# Test helper: run queries through the engine
# ================================================================

def run_queries(queries):
    """Send queries to the C++ engine and return output lines."""
    input_text = "\n".join(queries) + "\n"
    result = subprocess.run(
        [ENGINE],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=30
    )
    assert result.returncode == 0, f"Engine crashed: {result.stderr}"
    lines = result.stdout.strip().split("\n")
    assert len(lines) == len(queries), (
        f"Expected {len(queries)} output lines, got {len(lines)}: {result.stdout}"
    )
    return lines


# ================================================================
# Tests
# ================================================================

class TestBuild:
    def test_binary_exists(self):
        assert os.path.isfile(ENGINE), f"{ENGINE} not found"

    def test_binary_executable(self):
        assert os.access(ENGINE, os.X_OK), f"{ENGINE} not executable"


class TestGregorianRoundTrip:
    @pytest.mark.parametrize("y,m,d", [
        (1970, 1, 1),
        (2000, 1, 1),
        (2000, 2, 29),
        (1900, 2, 28),
        (2024, 12, 31),
        (1, 1, 1),
        (0, 3, 1),
        (-1, 12, 31),
        (400, 2, 29),
        (1600, 2, 29),
        (2000, 3, 1),
        (1999, 12, 31),
        (1582, 10, 15),
        (-400, 2, 29),
        (100, 2, 28),
        (2100, 2, 28),
        (1970, 2, 1),
        (1970, 2, 28),
        (2024, 2, 29),
        (1969, 12, 31),
    ])
    def test_roundtrip(self, y, m, d):
        queries = [f"CONVERT gregorian {y} {m} {d} gregorian"]
        lines = run_queries(queries)
        parts = lines[0].split()
        ry, rm, rd = int(parts[0]), int(parts[1]), int(parts[2])
        assert (ry, rm, rd) == (y, m, d)


class TestJulianRoundTrip:
    @pytest.mark.parametrize("y,m,d", [
        (1970, 1, 1),
        (2000, 1, 1),
        (2000, 2, 29),
        (1900, 2, 29),
        (1, 1, 1),
        (0, 1, 1),
        (-1, 1, 1),
        (100, 2, 29),
        (1582, 10, 5),
        (-400, 3, 1),
        (800, 2, 29),
    ])
    def test_roundtrip(self, y, m, d):
        queries = [f"CONVERT julian {y} {m} {d} julian"]
        lines = run_queries(queries)
        parts = lines[0].split()
        ry, rm, rd = int(parts[0]), int(parts[1]), int(parts[2])
        assert (ry, rm, rd) == (y, m, d)


class TestIslamicRoundTrip:
    @pytest.mark.parametrize("y,m,d", [
        (1, 1, 1),
        (1, 1, 30),
        (1, 2, 1),
        (1, 2, 29),
        (1, 12, 29),
        (2, 12, 30),
        (1446, 1, 1),
        (1400, 6, 15),
        (1, 6, 1),
        (1, 7, 1),
        (30, 12, 29),
        (31, 1, 1),
        (1, 4, 1),
        (1, 8, 1),
        (1, 10, 1),
        (1, 12, 1),
    ])
    def test_roundtrip(self, y, m, d):
        queries = [f"CONVERT islamic {y} {m} {d} islamic"]
        lines = run_queries(queries)
        parts = lines[0].split()
        ry, rm, rd = int(parts[0]), int(parts[1]), int(parts[2])
        assert (ry, rm, rd) == (y, m, d)


class TestCrossCalendarConversion:
    def _test_conversion(self, src, y1, m1, d1, dst, y2, m2, d2):
        queries = [f"CONVERT {src} {y1} {m1} {d1} {dst}"]
        lines = run_queries(queries)
        parts = lines[0].split()
        ry, rm, rd = int(parts[0]), int(parts[1]), int(parts[2])
        assert (ry, rm, rd) == (y2, m2, d2), (
            f"CONVERT {src} {y1}/{m1}/{d1} -> {dst}: "
            f"expected ({y2},{m2},{d2}), got ({ry},{rm},{rd})"
        )

    def test_gregorian_to_julian_known_dates(self):
        for y, m, d in [
            (2000, 1, 1), (2000, 3, 1), (1970, 1, 1),
            (1900, 3, 1), (1582, 10, 15), (2024, 6, 15),
            (1, 1, 1), (0, 3, 1), (-100, 6, 15),
        ]:
            serial = gregorian_to_days(y, m, d)
            jy, jm, jd = julian_from_days(serial)
            self._test_conversion("gregorian", y, m, d, "julian", jy, jm, jd)

    def test_julian_to_gregorian_known_dates(self):
        for y, m, d in [
            (2000, 1, 1), (1970, 1, 1), (1582, 10, 5),
            (1, 1, 1), (100, 2, 29),
        ]:
            serial = julian_to_days(y, m, d)
            gy, gm, gd = gregorian_from_days(serial)
            self._test_conversion("julian", y, m, d, "gregorian", gy, gm, gd)

    def test_gregorian_to_islamic_known_dates(self):
        for y, m, d in [
            (2000, 1, 1), (1970, 1, 1), (2024, 3, 11),
            (622, 7, 19),
        ]:
            serial = gregorian_to_days(y, m, d)
            iy, im, idd = islamic_from_days(serial)
            self._test_conversion("gregorian", y, m, d, "islamic", iy, im, idd)

    def test_islamic_epoch(self):
        serial = islamic_to_days(1, 1, 1)
        gy, gm, gd = gregorian_from_days(serial)
        self._test_conversion("islamic", 1, 1, 1, "gregorian", gy, gm, gd)
        expected_serial = gregorian_to_days(622, 7, 19)
        assert serial == expected_serial

    def test_gregorian_epoch(self):
        serial = gregorian_to_days(1970, 1, 1)
        assert serial == 0

    def test_february_cross_calendar(self):
        for y, m, d in [
            (2000, 2, 1), (2000, 2, 15), (2000, 2, 28), (2000, 2, 29),
            (1970, 2, 1), (1970, 2, 28), (2024, 2, 29),
        ]:
            serial = gregorian_to_days(y, m, d)
            jy, jm, jd = julian_from_days(serial)
            self._test_conversion("gregorian", y, m, d, "julian", jy, jm, jd)


class TestWeekday:
    @pytest.mark.parametrize("cal,y,m,d,expected_wd", [
        ("gregorian", 1970, 1, 1, 4),
        ("gregorian", 2000, 1, 1, 6),
        ("gregorian", 2024, 1, 1, 1),
        ("gregorian", 1969, 12, 31, 3),
        ("gregorian", 1969, 12, 28, 0),
        ("gregorian", 2024, 7, 4, 4),
        ("gregorian", 1, 1, 1, 1),
    ])
    def test_known_weekdays(self, cal, y, m, d, expected_wd):
        queries = [f"WEEKDAY {cal} {y} {m} {d}"]
        lines = run_queries(queries)
        wd = int(lines[0].strip())
        assert wd == expected_wd

    def test_weekday_consistency_with_reference(self):
        queries = []
        expected = []
        for serial in range(-1000, 1000, 7):
            y, m, d = gregorian_from_days(serial)
            queries.append(f"WEEKDAY gregorian {y} {m} {d}")
            expected.append(weekday_from_days(serial))
        lines = run_queries(queries)
        for i, (line, exp) in enumerate(zip(lines, expected)):
            wd = int(line.strip())
            assert wd == exp

    def test_weekday_negative_dates(self):
        queries = []
        expected = []
        for serial in [-5, -10, -100, -1000, -10000, -100000]:
            y, m, d = gregorian_from_days(serial)
            queries.append(f"WEEKDAY gregorian {y} {m} {d}")
            expected.append(weekday_from_days(serial))
        lines = run_queries(queries)
        for i, (line, exp) in enumerate(zip(lines, expected)):
            wd = int(line.strip())
            assert wd == exp

    def test_weekday_february_dates(self):
        queries = []
        expected = []
        for y in [2000, 2001, 1970, 1969, 1600, 100]:
            for d in [1, 14, 28]:
                serial = gregorian_to_days(y, 2, d)
                queries.append(f"WEEKDAY gregorian {y} 2 {d}")
                expected.append(weekday_from_days(serial))
        lines = run_queries(queries)
        for i, (line, exp) in enumerate(zip(lines, expected)):
            wd = int(line.strip())
            assert wd == exp


class TestISOWeekDate:
    @pytest.mark.parametrize("y,m,d,iy,iw,iwd", [
        (2005, 1, 1, 2004, 53, 6),
        (2004, 12, 31, 2004, 53, 5),
        (2004, 1, 1, 2004, 1, 4),
        (2010, 1, 1, 2009, 53, 5),
        (2009, 12, 31, 2009, 53, 4),
        (2024, 1, 1, 2024, 1, 1),
        (1970, 1, 1, 1970, 1, 4),
        (2023, 1, 1, 2022, 52, 7),
        (2023, 1, 2, 2023, 1, 1),
    ])
    def test_known_iso_weeks(self, y, m, d, iy, iw, iwd):
        queries = [f"ISO_WEEK {y} {m} {d}"]
        lines = run_queries(queries)
        parts = lines[0].split()
        got_iy, got_iw, got_iwd = int(parts[0]), int(parts[1]), int(parts[2])
        assert (got_iy, got_iw, got_iwd) == (iy, iw, iwd)

    def test_iso_week_consistency(self):
        queries = []
        expected = []
        for y in [2000, 2004, 2005, 2009, 2010, 2015, 2020, 2023, 2024]:
            for m, d in [(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7),
                         (12, 28), (12, 29), (12, 30), (12, 31)]:
                queries.append(f"ISO_WEEK {y} {m} {d}")
                expected.append(iso_week_from_gregorian(y, m, d))
        lines = run_queries(queries)
        for i, (line, exp) in enumerate(zip(lines, expected)):
            parts = line.split()
            got = (int(parts[0]), int(parts[1]), int(parts[2]))
            assert got == exp

    def test_from_iso_week_known(self):
        test_cases = [
            (2004, 53, 6, 2005, 1, 1),
            (2004, 1, 4, 2004, 1, 1),
            (2009, 53, 5, 2010, 1, 1),
            (1970, 1, 4, 1970, 1, 1),
            (2024, 1, 1, 2024, 1, 1),
        ]
        for iy, iw, iwd, gy, gm, gd in test_cases:
            queries = [f"FROM_ISO_WEEK {iy} {iw} {iwd}"]
            lines = run_queries(queries)
            parts = lines[0].split()
            got = (int(parts[0]), int(parts[1]), int(parts[2]))
            assert got == (gy, gm, gd)

    def test_iso_week_roundtrip(self):
        queries_iso = []
        dates = []
        for y in [2000, 2004, 2005, 2024, 1970]:
            for m in [1, 6, 12]:
                for d in [1, 15, 28]:
                    queries_iso.append(f"ISO_WEEK {y} {m} {d}")
                    dates.append((y, m, d))
        lines_iso = run_queries(queries_iso)
        queries_from = []
        for line in lines_iso:
            parts = line.split()
            queries_from.append(f"FROM_ISO_WEEK {parts[0]} {parts[1]} {parts[2]}")
        lines_from = run_queries(queries_from)
        for i, (line, (y, m, d)) in enumerate(zip(lines_from, dates)):
            parts = line.split()
            got = (int(parts[0]), int(parts[1]), int(parts[2]))
            assert got == (y, m, d)


class TestIslamicEvenMonths:
    def test_islamic_month_boundaries(self):
        queries = []
        expected = []
        for m in range(1, 13):
            serial = islamic_to_days(1, m, 1)
            gy, gm, gd = gregorian_from_days(serial)
            queries.append(f"CONVERT islamic 1 {m} 1 gregorian")
            expected.append((gy, gm, gd))
        lines = run_queries(queries)
        for i, (line, exp) in enumerate(zip(lines, expected)):
            parts = line.split()
            got = (int(parts[0]), int(parts[1]), int(parts[2]))
            m = i + 1
            assert got == exp, (
                f"Islamic month {m} day 1 -> Gregorian: expected {exp}, got {got}"
            )


class TestEraBoundaries:
    def test_gregorian_400_year_boundary(self):
        queries = []
        expected = []
        for y, m, d in [
            (400, 2, 29), (400, 3, 1), (0, 3, 1), (0, 2, 29),
            (800, 2, 29), (1200, 3, 1), (1600, 2, 29), (2000, 2, 29),
            (-400, 2, 29), (-400, 3, 1),
        ]:
            queries.append(f"CONVERT gregorian {y} {m} {d} gregorian")
            expected.append((y, m, d))
        lines = run_queries(queries)
        for i, (line, exp) in enumerate(zip(lines, expected)):
            parts = line.split()
            got = (int(parts[0]), int(parts[1]), int(parts[2]))
            assert got == exp

    def test_julian_4_year_boundary(self):
        queries = []
        expected = []
        for y, m, d in [
            (4, 2, 29), (4, 3, 1), (8, 2, 29), (100, 2, 29),
            (0, 2, 29), (-4, 2, 29),
        ]:
            queries.append(f"CONVERT julian {y} {m} {d} julian")
            expected.append((y, m, d))
        lines = run_queries(queries)
        for i, (line, exp) in enumerate(zip(lines, expected)):
            parts = line.split()
            got = (int(parts[0]), int(parts[1]), int(parts[2]))
            assert got == exp

    def test_islamic_30_year_boundary(self):
        queries = []
        expected = []
        for y in [1, 2, 30, 31, 60, 61]:
            queries.append(f"CONVERT islamic {y} 1 1 islamic")
            expected.append((y, 1, 1))
        lines = run_queries(queries)
        for i, (line, exp) in enumerate(zip(lines, expected)):
            parts = line.split()
            got = (int(parts[0]), int(parts[1]), int(parts[2]))
            assert got == exp


class TestSerialDayZero:
    def test_serial_zero_is_epoch(self):
        queries = [
            "CONVERT gregorian 1970 1 1 julian",
            "CONVERT gregorian 1970 1 1 islamic",
            "WEEKDAY gregorian 1970 1 1",
        ]
        lines = run_queries(queries)
        jy, jm, jd = julian_from_days(0)
        parts = lines[0].split()
        assert (int(parts[0]), int(parts[1]), int(parts[2])) == (jy, jm, jd)
        iy, im, idd = islamic_from_days(0)
        parts = lines[1].split()
        assert (int(parts[0]), int(parts[1]), int(parts[2])) == (iy, im, idd)
        assert int(lines[2].strip()) == 4


class TestExtendedRange:
    def test_large_positive_dates(self):
        queries = []
        expected = []
        for serial in [100000, 500000, 1000000]:
            y, m, d = gregorian_from_days(serial)
            queries.append(f"CONVERT gregorian {y} {m} {d} gregorian")
            expected.append((y, m, d))
        lines = run_queries(queries)
        for line, exp in zip(lines, expected):
            parts = line.split()
            got = (int(parts[0]), int(parts[1]), int(parts[2]))
            assert got == exp

    def test_large_negative_dates(self):
        queries = []
        expected = []
        for serial in [-100000, -500000, -1000000]:
            y, m, d = gregorian_from_days(serial)
            queries.append(f"CONVERT gregorian {y} {m} {d} gregorian")
            expected.append((y, m, d))
        lines = run_queries(queries)
        for line, exp in zip(lines, expected):
            parts = line.split()
            got = (int(parts[0]), int(parts[1]), int(parts[2]))
            assert got == exp


# ================================================================
# Timezone tests
# ================================================================

class TestTZOffsetNoDST:
    """Zones without DST should always return standard offset."""

    @pytest.mark.parametrize("m,d,h", [
        (1, 15, 0), (6, 15, 12), (12, 31, 23),
    ])
    def test_tokyo_always_standard(self, m, d, h):
        queries = [f"TZ_OFFSET Asia/Tokyo 2024 {m} {d} {h} 0"]
        lines = run_queries(queries)
        assert int(lines[0].strip()) == 540


class TestTZOffsetNorthern:
    """Northern hemisphere DST tests."""

    @pytest.mark.parametrize("zone,y,m,d,h,expected", [
        ("America/New_York", 2024, 1, 15, 12, -300),
        ("America/New_York", 2024, 7, 15, 12, -240),
        ("Europe/London", 2024, 2, 15, 12, 0),
        ("Europe/London", 2024, 6, 15, 12, 60),
        ("Europe/Berlin", 2024, 8, 1, 10, 120),
        ("Europe/Berlin", 2024, 12, 1, 10, 60),
        ("America/Los_Angeles", 2024, 1, 10, 8, -480),
        ("America/Los_Angeles", 2024, 5, 20, 14, -420),
    ])
    def test_northern_dst(self, zone, y, m, d, h, expected):
        queries = [f"TZ_OFFSET {zone} {y} {m} {d} {h} 0"]
        lines = run_queries(queries)
        assert int(lines[0].strip()) == expected, (
            f"TZ_OFFSET {zone} {y}-{m:02d}-{d:02d} {h}:00: "
            f"expected {expected}, got {lines[0].strip()}"
        )


class TestTZOffsetTransitionBoundary:
    """Test exact DST transition hour boundaries."""

    def test_ny_spring_at_transition_hour(self):
        """2nd Sunday of March 2024 = March 10. At 2:00 AM DST begins."""
        queries = [f"TZ_OFFSET America/New_York 2024 3 10 2 0"]
        lines = run_queries(queries)
        assert int(lines[0].strip()) == -240, "DST should be active AT 2:00 AM"

    def test_ny_spring_before_transition(self):
        queries = [f"TZ_OFFSET America/New_York 2024 3 10 1 0"]
        lines = run_queries(queries)
        assert int(lines[0].strip()) == -300

    def test_london_spring_at_transition_hour(self):
        """Last Sunday of March 2024 = March 31. At 1:00 AM DST begins."""
        queries = [f"TZ_OFFSET Europe/London 2024 3 31 1 0"]
        lines = run_queries(queries)
        assert int(lines[0].strip()) == 60

    def test_london_spring_before_transition(self):
        queries = [f"TZ_OFFSET Europe/London 2024 3 31 0 0"]
        lines = run_queries(queries)
        assert int(lines[0].strip()) == 0

    def test_ny_fall_back_before_end(self):
        """1st Sunday of November 2024 = Nov 3. Before 2:00 AM is still DST."""
        queries = [f"TZ_OFFSET America/New_York 2024 11 3 1 0"]
        lines = run_queries(queries)
        assert int(lines[0].strip()) == -240

    def test_ny_fall_back_at_end(self):
        """At 2:00 AM fall back, DST ends."""
        queries = [f"TZ_OFFSET America/New_York 2024 11 3 2 0"]
        lines = run_queries(queries)
        assert int(lines[0].strip()) == -300


class TestTZOffsetSouthern:
    """Southern hemisphere DST (wraps around year boundary)."""

    @pytest.mark.parametrize("m,d,h,expected", [
        (1, 15, 12, 660),    # Jan = summer = DST
        (3, 15, 12, 660),    # Mar = still DST
        (7, 15, 12, 600),    # Jul = winter = standard
        (9, 15, 12, 600),    # Sep = still standard
        (11, 15, 12, 660),   # Nov = after Oct start = DST
    ])
    def test_sydney_dst(self, m, d, h, expected):
        queries = [f"TZ_OFFSET Australia/Sydney 2024 {m} {d} {h} 0"]
        lines = run_queries(queries)
        assert int(lines[0].strip()) == expected, (
            f"Australia/Sydney 2024-{m:02d}-{d:02d} {h}:00: "
            f"expected {expected}, got {lines[0].strip()}"
        )

    def test_sydney_transition_start(self):
        """1st Sunday of October 2024 = Oct 6. At 2:00 AM DST starts."""
        queries = [f"TZ_OFFSET Australia/Sydney 2024 10 6 2 0"]
        lines = run_queries(queries)
        assert int(lines[0].strip()) == 660

    def test_sydney_before_transition_start(self):
        queries = [f"TZ_OFFSET Australia/Sydney 2024 10 6 1 0"]
        lines = run_queries(queries)
        assert int(lines[0].strip()) == 600


class TestToUTC:
    """TO_UTC conversion tests."""

    @pytest.mark.parametrize("zone,y,m,d,h,min_", [
        ("America/New_York", 2024, 7, 15, 14, 30),
        ("Asia/Tokyo", 2024, 1, 15, 3, 0),
        ("Europe/London", 2024, 6, 1, 10, 45),
        ("Australia/Sydney", 2024, 1, 1, 0, 30),
        ("America/Los_Angeles", 2024, 12, 25, 23, 59),
    ])
    def test_to_utc(self, zone, y, m, d, h, min_):
        expected = py_to_utc(zone, y, m, d, h, min_)
        queries = [f"TO_UTC {zone} {y} {m} {d} {h} {min_}"]
        lines = run_queries(queries)
        parts = lines[0].split()
        got = (int(parts[0]), int(parts[1]), int(parts[2]),
               int(parts[3]), int(parts[4]))
        assert got == expected, f"TO_UTC: expected {expected}, got {got}"

    def test_to_utc_day_rollover_backward(self):
        """Tokyo 3:00 AM = previous day 18:00 UTC."""
        expected = py_to_utc("Asia/Tokyo", 2024, 6, 15, 3, 0)
        queries = ["TO_UTC Asia/Tokyo 2024 6 15 3 0"]
        lines = run_queries(queries)
        parts = lines[0].split()
        got = (int(parts[0]), int(parts[1]), int(parts[2]),
               int(parts[3]), int(parts[4]))
        assert got == expected

    def test_to_utc_day_rollover_forward(self):
        """LA 11:59 PM PST (Dec, standard) = next day UTC."""
        expected = py_to_utc("America/Los_Angeles", 2024, 12, 31, 23, 59)
        queries = ["TO_UTC America/Los_Angeles 2024 12 31 23 59"]
        lines = run_queries(queries)
        parts = lines[0].split()
        got = (int(parts[0]), int(parts[1]), int(parts[2]),
               int(parts[3]), int(parts[4]))
        assert got == expected

    def test_to_utc_multiple_zones(self):
        """Same local time, different zones, should give different UTC."""
        queries = []
        expected_list = []
        for zone in ["America/New_York", "Europe/London", "Asia/Tokyo"]:
            queries.append(f"TO_UTC {zone} 2024 6 15 12 0")
            expected_list.append(py_to_utc(zone, 2024, 6, 15, 12, 0))
        lines = run_queries(queries)
        for i, (line, exp) in enumerate(zip(lines, expected_list)):
            parts = line.split()
            got = (int(parts[0]), int(parts[1]), int(parts[2]),
                   int(parts[3]), int(parts[4]))
            assert got == exp
