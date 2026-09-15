
"""
Tests for HdrHistogram and HistogramCodec implementation.
Runs the compiled Java class via subprocess and verifies exact numerical invariants.
"""

import subprocess
import pytest
import os
import textwrap

CLASSPATH = "/app/classes"
JAVA = "java"


def run_java(code: str) -> str:
    """Write a temporary Java program that uses HdrHistogram, compile, and run it."""
    test_file = "/tmp/TestHdr.java"
    with open(test_file, "w") as f:
        f.write(code)
    result = subprocess.run(
        ["javac", "-cp", CLASSPATH, test_file, "-d", "/tmp/testclasses"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"Compilation failed:\n{result.stderr}")
    result = subprocess.run(
        [JAVA, "-cp", f"{CLASSPATH}:/tmp/testclasses", "TestHdr"],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"Runtime error:\n{result.stderr}\n{result.stdout}")
    return result.stdout.strip()


def setup_module(module):
    os.makedirs("/tmp/testclasses", exist_ok=True)
    # Verify base compilation succeeded
    assert os.path.exists(os.path.join(CLASSPATH, "HdrHistogram.class")), \
        "HdrHistogram.class not found — compilation must succeed first"
    assert os.path.exists(os.path.join(CLASSPATH, "HistogramCodec.class")), \
        "HistogramCodec.class not found — compilation must succeed first"


# ============================================================
# Test 1: Construction argument validation
# ============================================================
class TestConstructionValidation:

    def test_highest_too_low(self):
        """highestTrackableValue < 2 * lowestDiscernibleValue should throw"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    try {
                        new HdrHistogram(1, 3);
                        System.out.println("NO_EXCEPTION");
                    } catch (IllegalArgumentException e) {
                        System.out.println("CAUGHT_IAE");
                    }
                }
            }
        """)
        assert run_java(code) == "CAUGHT_IAE"

    def test_digits_too_high(self):
        """numberOfSignificantValueDigits > 5 should throw"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    try {
                        new HdrHistogram(3600000000L, 6);
                        System.out.println("NO_EXCEPTION");
                    } catch (IllegalArgumentException e) {
                        System.out.println("CAUGHT_IAE");
                    }
                }
            }
        """)
        assert run_java(code) == "CAUGHT_IAE"

    def test_digits_negative(self):
        """numberOfSignificantValueDigits < 0 should throw"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    try {
                        new HdrHistogram(3600000000L, -1);
                        System.out.println("NO_EXCEPTION");
                    } catch (IllegalArgumentException e) {
                        System.out.println("CAUGHT_IAE");
                    }
                }
            }
        """)
        assert run_java(code) == "CAUGHT_IAE"

    def test_unit_magnitude_52_throws(self):
        """unitMagnitude 52 with 3 significant digits should throw (subBucketCountMagnitude + unitMagnitude > 62)"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    try {
                        new HdrHistogram(1L << 52, 1L << 62, 3);
                        System.out.println("NO_EXCEPTION");
                    } catch (IllegalArgumentException e) {
                        System.out.println("CAUGHT_IAE");
                    }
                }
            }
        """)
        assert run_java(code) == "CAUGHT_IAE"

    def test_valid_construction(self):
        """Valid construction should succeed and return correct parameters"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    System.out.println(h.getLowestDiscernibleValue());
                    System.out.println(h.getHighestTrackableValue());
                    System.out.println(h.getNumberOfSignificantValueDigits());
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "1"
        assert lines[1] == "3600000000"
        assert lines[2] == "3"


# ============================================================
# Test 2: Unit magnitude 0 index calculations
# ============================================================
class TestUnitMagnitude0:

    def test_structure(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1L, 1L << 32, 3);
                    System.out.println(h.subBucketCount);
                    System.out.println(h.unitMagnitude);
                    System.out.println(h.bucketCount);
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "2048"
        assert lines[1] == "0"
        assert lines[2] == "23"

    def test_index_calculations(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1L, 1L << 32, 3);
                    // first half of first bucket
                    System.out.println(h.getBucketIndex(3));
                    System.out.println(h.getSubBucketIndex(3, 0));
                    // second half of first bucket
                    System.out.println(h.getBucketIndex(1024 + 3));
                    System.out.println(h.getSubBucketIndex(1024 + 3, 0));
                    // second bucket (top half)
                    System.out.println(h.getBucketIndex(2048 + 3 * 2));
                    System.out.println(h.getSubBucketIndex(2048 + 3 * 2, 1));
                    // third bucket (top half)
                    System.out.println(h.getBucketIndex((2048 << 1) + 3 * 4));
                    System.out.println(h.getSubBucketIndex((2048 << 1) + 3 * 4, 2));
                    // past last bucket
                    System.out.println(h.getBucketIndex((2048L << 22) + 3 * (1 << 23)));
                    System.out.println(h.getSubBucketIndex((2048L << 22) + 3 * (1 << 23), 23));
                }
            }
        """)
        lines = run_java(code).split("\n")
        expected = ["0", "3", "0", "1027", "1", "1027", "2", "1027", "23", "1027"]
        assert lines == expected


# ============================================================
# Test 3: Unit magnitude 4 (lowestDiscernibleValue = 1 << 12)
# ============================================================
class TestUnitMagnitude4:

    def test_structure_and_indices(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1L << 12, 1L << 32, 3);
                    System.out.println(h.subBucketCount);
                    System.out.println(h.unitMagnitude);
                    System.out.println(h.bucketCount);
                    long unit = 1L << 12;
                    // below lowest value
                    System.out.println(h.getBucketIndex(3));
                    System.out.println(h.getSubBucketIndex(3, 0));
                    // first half
                    System.out.println(h.getBucketIndex(3 * unit));
                    System.out.println(h.getSubBucketIndex(3 * unit, 0));
                    // second half
                    System.out.println(h.getBucketIndex(unit * (1024 + 3)));
                    System.out.println(h.getSubBucketIndex(unit * (1024 + 3), 0));
                    // second bucket
                    System.out.println(h.getBucketIndex((unit << 11) + 3 * (unit << 1)));
                    System.out.println(h.getSubBucketIndex((unit << 11) + 3 * (unit << 1), 1));
                }
            }
        """)
        lines = run_java(code).split("\n")
        expected = ["2048", "12", "11",
                    "0", "0",
                    "0", "3",
                    "0", "1027",
                    "1", "1027"]
        assert lines == expected


# ============================================================
# Test 4: Unit magnitude 51 (extreme near Long.MAX_VALUE)
# ============================================================
class TestUnitMagnitude51:

    def test_structure_and_long_max(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1L << 51, Long.MAX_VALUE, 3);
                    System.out.println(h.subBucketCount);
                    System.out.println(h.unitMagnitude);
                    System.out.println(h.bucketCount);
                    System.out.println(h.leadingZeroCountBase);
                    long unit = 1L << 51;
                    // below lowest
                    System.out.println(h.getBucketIndex(3));
                    System.out.println(h.getSubBucketIndex(3, 0));
                    // first half
                    System.out.println(h.getBucketIndex(3 * unit));
                    System.out.println(h.getSubBucketIndex(3 * unit, 0));
                    // Long.MAX_VALUE
                    System.out.println(h.getBucketIndex(Long.MAX_VALUE));
                    System.out.println(h.getSubBucketIndex(Long.MAX_VALUE, 1));
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "2048"
        assert lines[1] == "51"
        assert lines[2] == "2"
        assert lines[3] == "2"
        assert lines[4] == "0"
        assert lines[5] == "0"
        assert lines[6] == "0"
        assert lines[7] == "3"
        assert lines[8] == "1"
        assert lines[9] == str(1024 + 1023)


# ============================================================
# Test 5: Unit magnitude 54 with 2 digits, and 61 with 0 digits
# ============================================================
class TestExtremeUnitMagnitudes:

    def test_unit_mag_54_digits_2(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1L << 54, 1L << 62, 2);
                    System.out.println(h.subBucketCount);
                    System.out.println(h.unitMagnitude);
                    System.out.println(h.bucketCount);
                    System.out.println(h.getBucketIndex(3));
                    System.out.println(h.getSubBucketIndex(3, 0));
                    System.out.println(h.getBucketIndex(Long.MAX_VALUE));
                    System.out.println(h.getSubBucketIndex(Long.MAX_VALUE, 1));
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "256"
        assert lines[1] == "54"
        assert lines[2] == "2"
        assert lines[5] == "1"
        assert lines[6] == str(128 + 127)

    def test_unit_mag_61_digits_0(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1L << 61, 1L << 62, 0);
                    System.out.println(h.subBucketCount);
                    System.out.println(h.unitMagnitude);
                    System.out.println(h.bucketCount);
                    System.out.println(h.getBucketIndex(Long.MAX_VALUE));
                    System.out.println(h.getSubBucketIndex(Long.MAX_VALUE, 1));
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "2"
        assert lines[1] == "61"
        assert lines[2] == "2"
        assert lines[3] == "1"
        assert lines[4] == "1"


# ============================================================
# Test 6: Record value and basic counting
# ============================================================
class TestRecordValue:

    def test_basic_record(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    h.recordValue(4);
                    System.out.println(h.getCountAtValue(4));
                    System.out.println(h.getTotalCount());
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "1"
        assert lines[1] == "1"

    def test_overflow_throws(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    try {
                        HdrHistogram h = new HdrHistogram(3600000000L, 3);
                        h.recordValue(3600000000L * 3);
                        System.out.println("NO_EXCEPTION");
                    } catch (ArrayIndexOutOfBoundsException e) {
                        System.out.println("CAUGHT_AIOOBE");
                    }
                }
            }
        """)
        assert run_java(code) == "CAUGHT_AIOOBE"


# ============================================================
# Test 7: Coordinated omission correction
# ============================================================
class TestCoordinatedOmission:

    def test_record_with_expected_interval(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    long testValueLevel = 4;
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    h.recordValueWithExpectedInterval(testValueLevel, testValueLevel / 4);
                    System.out.println(h.getCountAtValue((testValueLevel * 1) / 4));
                    System.out.println(h.getCountAtValue((testValueLevel * 2) / 4));
                    System.out.println(h.getCountAtValue((testValueLevel * 3) / 4));
                    System.out.println(h.getCountAtValue((testValueLevel * 4) / 4));
                    System.out.println(h.getTotalCount());
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "1"
        assert lines[1] == "1"
        assert lines[2] == "1"
        assert lines[3] == "1"
        assert lines[4] == "4"


# ============================================================
# Test 8: Equivalent value range methods
# ============================================================
class TestEquivalentValues:

    def test_size_of_equivalent_value_range(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    System.out.println(h.sizeOfEquivalentValueRange(1));
                    System.out.println(h.sizeOfEquivalentValueRange(1025));
                    System.out.println(h.sizeOfEquivalentValueRange(2047));
                    System.out.println(h.sizeOfEquivalentValueRange(2048));
                    System.out.println(h.sizeOfEquivalentValueRange(2500));
                    System.out.println(h.sizeOfEquivalentValueRange(8191));
                    System.out.println(h.sizeOfEquivalentValueRange(8192));
                    System.out.println(h.sizeOfEquivalentValueRange(10000));
                }
            }
        """)
        lines = run_java(code).split("\n")
        expected = ["1", "1", "1", "2", "2", "4", "8", "8"]
        assert lines == expected

    def test_lowest_equivalent(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    System.out.println(h.lowestEquivalentValue(10007));
                    System.out.println(h.lowestEquivalentValue(10009));
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "10000"
        assert lines[1] == "10008"

    def test_highest_equivalent(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    System.out.println(h.highestEquivalentValue(8180));
                    System.out.println(h.highestEquivalentValue(8191));
                    System.out.println(h.highestEquivalentValue(8193));
                    System.out.println(h.highestEquivalentValue(9995));
                    System.out.println(h.highestEquivalentValue(10007));
                    System.out.println(h.highestEquivalentValue(10008));
                }
            }
        """)
        lines = run_java(code).split("\n")
        expected = ["8183", "8191", "8199", "9999", "10007", "10015"]
        assert lines == expected

    def test_median_equivalent(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    System.out.println(h.medianEquivalentValue(4));
                    System.out.println(h.medianEquivalentValue(5));
                    System.out.println(h.medianEquivalentValue(4000));
                    System.out.println(h.medianEquivalentValue(8000));
                    System.out.println(h.medianEquivalentValue(10007));
                }
            }
        """)
        lines = run_java(code).split("\n")
        expected = ["4", "5", "4001", "8002", "10004"]
        assert lines == expected


# ============================================================
# Test 9: Scaled equivalent values (lowestDiscernibleValue = 1024)
# ============================================================
class TestScaledEquivalent:

    def test_scaled_size_of_range(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1024, 3600000000L, 3);
                    System.out.println(h.sizeOfEquivalentValueRange(1 * 1024));
                    System.out.println(h.sizeOfEquivalentValueRange(2500 * 1024));
                    System.out.println(h.sizeOfEquivalentValueRange(8191 * 1024));
                    System.out.println(h.sizeOfEquivalentValueRange(8192 * 1024));
                    System.out.println(h.sizeOfEquivalentValueRange(10000 * 1024));
                }
            }
        """)
        lines = run_java(code).split("\n")
        expected = [str(1 * 1024), str(2 * 1024), str(4 * 1024), str(8 * 1024), str(8 * 1024)]
        assert lines == expected

    def test_scaled_highest_equivalent(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1024, 3600000000L, 3);
                    System.out.println(h.highestEquivalentValue(8180 * 1024));
                    System.out.println(h.highestEquivalentValue(8191 * 1024));
                    System.out.println(h.highestEquivalentValue(8193 * 1024));
                    System.out.println(h.highestEquivalentValue(9995 * 1024));
                    System.out.println(h.highestEquivalentValue(10007 * 1024));
                    System.out.println(h.highestEquivalentValue(10008 * 1024));
                }
            }
        """)
        lines = run_java(code).split("\n")
        expected = [
            str(8183 * 1024 + 1023),
            str(8191 * 1024 + 1023),
            str(8199 * 1024 + 1023),
            str(9999 * 1024 + 1023),
            str(10007 * 1024 + 1023),
            str(10015 * 1024 + 1023),
        ]
        assert lines == expected


# ============================================================
# Test 10: Value at percentile matches percentile contract
# ============================================================
class TestValueAtPercentile:

    def test_large_numbers(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(20000000, 100000000, 5);
                    h.recordValue(100000000);
                    h.recordValue(20000000);
                    h.recordValue(30000000);
                    System.out.println(h.valuesAreEquivalent(20000000, h.getValueAtPercentile(50.0)));
                    System.out.println(h.valuesAreEquivalent(30000000, h.getValueAtPercentile(50.0)));
                    System.out.println(h.valuesAreEquivalent(100000000, h.getValueAtPercentile(83.33)));
                    System.out.println(h.valuesAreEquivalent(100000000, h.getValueAtPercentile(83.34)));
                    System.out.println(h.valuesAreEquivalent(100000000, h.getValueAtPercentile(99.0)));
                }
            }
        """)
        lines = run_java(code).split("\n")
        for line in lines:
            assert line == "true", f"Expected true, got {line}"

    def test_percentile_matches_significant_digits_contract(self):
        """For each recorded value, getValueAtPercentile(calculatedPercentile) should be equivalent to that value."""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1, Long.MAX_VALUE, 2);
                    long[] lengths = {1, 5, 10, 50, 100, 500, 1000, 5000};
                    int failures = 0;
                    for (long length : lengths) {
                        h.reset();
                        for (long v = 1; v <= length; v++) {
                            h.recordValue(v);
                        }
                        for (long v = 1; v <= length; v = h.nextNonEquivalentValue(v)) {
                            double calcPct = 100.0 * ((double) v) / length;
                            long lookup = h.getValueAtPercentile(calcPct);
                            if (!h.valuesAreEquivalent(v, lookup)) {
                                failures++;
                            }
                        }
                    }
                    System.out.println(failures);
                }
            }
        """)
        assert run_java(code) == "0"


# ============================================================
# Test 11: Empty histogram behavior
# ============================================================
class TestEmptyHistogram:

    def test_empty_stats(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    System.out.println(h.getMinValue());
                    System.out.println(h.getMaxValue());
                    System.out.println(h.getMean());
                    System.out.println(h.getStdDeviation());
                    System.out.println(h.getPercentileAtOrBelowValue(0));
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "0"
        assert lines[1] == "0"
        assert lines[2] == "0.0"
        assert lines[3] == "0.0"
        assert lines[4] == "100.0"


# ============================================================
# Test 12: Add and subtract
# ============================================================
class TestHistogramArithmetic:

    def test_add(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    long htv = 3600000000L;
                    HdrHistogram h = new HdrHistogram(htv, 3);
                    HdrHistogram other = new HdrHistogram(htv, 3);
                    h.recordValue(4);
                    h.recordValue(4000);
                    other.recordValue(4);
                    other.recordValue(4000);
                    h.add(other);
                    System.out.println(h.getCountAtValue(4));
                    System.out.println(h.getCountAtValue(4000));
                    System.out.println(h.getTotalCount());
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "2"
        assert lines[1] == "2"
        assert lines[2] == "4"

    def test_subtract_to_zero(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    long htv = 3600000000L;
                    HdrHistogram h = new HdrHistogram(htv, 3);
                    h.recordValue(4);
                    h.recordValue(4000);
                    // Create identical copy to subtract
                    HdrHistogram copy = new HdrHistogram(htv, 3);
                    copy.recordValue(4);
                    copy.recordValue(4000);
                    h.subtract(copy);
                    System.out.println(h.getCountAtValue(4));
                    System.out.println(h.getCountAtValue(4000));
                    System.out.println(h.getTotalCount());
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "0"
        assert lines[1] == "0"
        assert lines[2] == "0"

    def test_subtract_negative_throws(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    long htv = 3600000000L;
                    HdrHistogram h = new HdrHistogram(htv, 3);
                    HdrHistogram other = new HdrHistogram(htv, 3);
                    h.recordValue(4);
                    other.recordValueWithCount(4, 2);
                    try {
                        h.subtract(other);
                        System.out.println("NO_EXCEPTION");
                    } catch (IllegalArgumentException e) {
                        System.out.println("CAUGHT_IAE");
                    }
                }
            }
        """)
        assert run_java(code) == "CAUGHT_IAE"


# ============================================================
# Test 13: Reset
# ============================================================
class TestReset:

    def test_reset_clears_state(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    h.recordValue(4);
                    h.recordValue(10);
                    h.recordValue(100);
                    h.reset();
                    System.out.println(h.getCountAtValue(4));
                    System.out.println(h.getTotalCount());
                    // After reset, record new values
                    h.recordValue(20);
                    h.recordValue(80);
                    System.out.println(h.getMinValue());
                    System.out.println(h.getMaxValue());
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "0"
        assert lines[1] == "0"
        assert lines[2] == "20"
        # maxValue should be highestEquivalent(80) = 80 (since within sub-bucket precision at that level)
        max_val = int(lines[3])
        assert max_val >= 80


# ============================================================
# Test 14: Estimated footprint
# ============================================================
class TestEstimatedFootprint:

    def test_footprint_formula(self):
        """Verify estimated footprint matches the known formula"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    long htv = 3600000000L;
                    int digits = 3;
                    HdrHistogram h = new HdrHistogram(htv, digits);
                    long largestWithSingleUnit = 2 * (long) Math.pow(10, digits);
                    int subBucketCountMag = (int) Math.ceil(Math.log(largestWithSingleUnit) / Math.log(2));
                    int subBucketSize = (int) Math.pow(2, subBucketCountMag);
                    long expected = 512 +
                        ((8 *
                            ((long)(Math.ceil(
                                Math.log(htv / subBucketSize) / Math.log(2)
                            ) + 2)) *
                            (1 << (64 - Long.numberOfLeadingZeros(2 * (long) Math.pow(10, digits))))
                        ) / 2);
                    System.out.println(expected);
                    System.out.println(h.getEstimatedFootprintInBytes());
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == lines[1], f"Expected {lines[0]} but got {lines[1]}"


# ============================================================
# Test 15: Mean and standard deviation
# ============================================================
class TestStatistics:

    def test_mean_simple(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    // Record values that all fall in unit-resolution range
                    for (int i = 1; i <= 100; i++) {
                        h.recordValue(i);
                    }
                    double mean = h.getMean();
                    // Mean of 1..100 is 50.5; at unit resolution each value maps to itself
                    // median equivalent of each value at unit resolution = value itself
                    System.out.println(mean >= 50.0 && mean <= 51.0);
                }
            }
        """)
        assert run_java(code) == "true"

    def test_stddev_zero_for_single(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    h.recordValueWithCount(42, 1000);
                    double stddev = h.getStdDeviation();
                    System.out.println(stddev < 0.001);
                }
            }
        """)
        assert run_java(code) == "true"


# ============================================================
# Test 16: percentileAtOrBelowValue
# ============================================================
class TestPercentileAt:

    def test_basic(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    for (int i = 1; i <= 100; i++) {
                        h.recordValue(i);
                    }
                    // All 100 values are <= 100, so percentile at 100 should be 100.0
                    System.out.println(h.getPercentileAtOrBelowValue(100));
                    // 50 values are <= 50
                    double pct50 = h.getPercentileAtOrBelowValue(50);
                    System.out.println(pct50 >= 49.0 && pct50 <= 51.0);
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "100.0"
        assert lines[1] == "true"


# ============================================================
# Test 17: valueFromIndex round-trip consistency
# ============================================================
class TestValueIndexRoundTrip:

    def test_round_trip(self):
        """For every index, countsArrayIndex(valueFromIndex(i)) should equal i (for valid indices)."""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1, 1L << 32, 3);
                    int failures = 0;
                    // Test first 5000 indices and last 100
                    int limit = Math.min(5000, h.countsArrayLength);
                    for (int i = 0; i < limit; i++) {
                        long v = h.valueFromIndex(i);
                        int idx = h.countsArrayIndex(v);
                        if (idx != i) failures++;
                    }
                    for (int i = Math.max(limit, h.countsArrayLength - 100); i < h.countsArrayLength; i++) {
                        long v = h.valueFromIndex(i);
                        int idx = h.countsArrayIndex(v);
                        if (idx != i) failures++;
                    }
                    System.out.println(failures);
                }
            }
        """)
        assert run_java(code) == "0"


# ============================================================
# Test 18: getCountAtValue for non-recorded value
# ============================================================
class TestCountAtValue:

    def test_unrecorded_returns_zero(self):
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    h.recordValue(100);
                    System.out.println(h.getCountAtValue(200));
                    System.out.println(h.getCountAtValue(100));
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "0"
        assert lines[1] == "1"


# ============================================================
# Test 19: Structural field verification across configurations
# ============================================================
class TestStructuralFields:

    def test_counts_array_length_various_configs(self):
        """Verify countsArrayLength and structural fields are correct for several configurations"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    // Config 1: default ldv=1, htv=3600000000, digits=3
                    HdrHistogram h1 = new HdrHistogram(3600000000L, 3);
                    System.out.println(h1.countsArrayLength);
                    System.out.println(h1.subBucketHalfCountMagnitude);
                    System.out.println(h1.leadingZeroCountBase);

                    // Config 2: ldv=1, htv=Long.MAX_VALUE, digits=5
                    HdrHistogram h2 = new HdrHistogram(1, Long.MAX_VALUE, 5);
                    System.out.println(h2.countsArrayLength);
                    System.out.println(h2.subBucketCount);
                    System.out.println(h2.bucketCount);

                    // Config 3: ldv=1, htv=1000, digits=0
                    HdrHistogram h3 = new HdrHistogram(1, 1000, 0);
                    System.out.println(h3.countsArrayLength);
                    System.out.println(h3.subBucketCount);
                    System.out.println(h3.bucketCount);
                }
            }
        """)
        lines = run_java(code).split("\n")
        # Config 1
        assert lines[0] == "23552"
        assert lines[1] == "10"
        assert lines[2] == "53"
        # Config 2
        assert lines[3] == "6160384"
        assert lines[4] == "262144"
        assert lines[5] == "46"
        # Config 3
        assert lines[6] == "11"
        assert lines[7] == "2"
        assert lines[8] == "10"


# ============================================================
# Test 20: Percentile edge cases (0th and 100th)
# ============================================================
class TestPercentileEdgeCases:

    def test_0th_percentile(self):
        """0th percentile should return lowestEquivalentValue of the minimum recorded value"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    h.recordValue(100);
                    h.recordValue(200);
                    h.recordValue(300);
                    long p0 = h.getValueAtPercentile(0.0);
                    System.out.println(h.lowestEquivalentValue(p0) == h.lowestEquivalentValue(100));
                }
            }
        """)
        assert run_java(code) == "true"

    def test_100th_percentile(self):
        """100th percentile should return highestEquivalentValue of the max value"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    h.recordValue(100);
                    h.recordValue(200);
                    h.recordValue(1000000);
                    long p100 = h.getValueAtPercentile(100.0);
                    System.out.println(h.valuesAreEquivalent(p100, 1000000));
                }
            }
        """)
        assert run_java(code) == "true"


# ============================================================
# Test 21: Multi-step add/subtract workflow
# ============================================================
class TestMultiStepWorkflow:

    def test_add_then_subtract_restores_state(self):
        """Adding then subtracting the same histogram should restore original counts"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram base = new HdrHistogram(3600000000L, 3);
                    base.recordValue(100);
                    base.recordValue(500);
                    base.recordValue(10000);

                    HdrHistogram delta = new HdrHistogram(3600000000L, 3);
                    delta.recordValue(200);
                    delta.recordValue(300);

                    base.add(delta);
                    System.out.println(base.getTotalCount());
                    base.subtract(delta);
                    System.out.println(base.getTotalCount());
                    System.out.println(base.getCountAtValue(200));
                    System.out.println(base.getCountAtValue(100));
                    System.out.println(base.getCountAtValue(10000));
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "5"
        assert lines[1] == "3"
        assert lines[2] == "0"
        assert lines[3] == "1"
        assert lines[4] == "1"


# ============================================================
# Test 22: Min/max tracking across subtract operations
# ============================================================
class TestMinMaxTracking:

    def test_min_after_subtract_of_min_value(self):
        """After subtracting the min value, min should update to next recorded value"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    h.recordValue(10);
                    h.recordValue(100);
                    h.recordValue(1000);
                    System.out.println(h.getMinValue());

                    HdrHistogram sub = new HdrHistogram(3600000000L, 3);
                    sub.recordValue(10);
                    h.subtract(sub);
                    long newMin = h.getMinValue();
                    System.out.println(h.valuesAreEquivalent(newMin, 100));
                    System.out.println(h.getTotalCount());
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "10"
        assert lines[1] == "true"
        assert lines[2] == "2"

    def test_max_after_subtract_of_max_value(self):
        """After subtracting the max value, max should update to next highest recorded value"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    h.recordValue(10);
                    h.recordValue(100);
                    h.recordValue(1000);

                    HdrHistogram sub = new HdrHistogram(3600000000L, 3);
                    sub.recordValue(1000);
                    h.subtract(sub);
                    long newMax = h.getMaxValue();
                    System.out.println(h.valuesAreEquivalent(newMax, 100));
                }
            }
        """)
        assert run_java(code) == "true"


# ============================================================
# Test 23: Recording at boundary values
# ============================================================
class TestBoundaryRecording:

    def test_record_at_highest_trackable(self):
        """Recording exactly at highestTrackableValue should succeed"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    long htv = 3600000000L;
                    HdrHistogram h = new HdrHistogram(htv, 3);
                    h.recordValue(htv);
                    System.out.println(h.getTotalCount());
                    System.out.println(h.getCountAtValue(htv) >= 1);
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "1"
        assert lines[1] == "true"

    def test_record_zero(self):
        """Recording 0 should work and affect min value"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    h.recordValue(0);
                    h.recordValue(100);
                    System.out.println(h.getTotalCount());
                    System.out.println(h.getMinValue());
                    System.out.println(h.getCountAtValue(0));
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "2"
        assert lines[1] == "0"
        assert lines[2] == "1"


# ============================================================
# Test 24: Percentile accuracy across many exponential buckets
# ============================================================
class TestCrossBucketPercentile:

    def test_percentile_across_orders_of_magnitude(self):
        """Verify percentile accuracy when values span many orders of magnitude"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1, Long.MAX_VALUE, 3);
                    long[] values = {1, 10, 100, 1000, 10000, 100000, 1000000,
                                     10000000, 100000000, 1000000000L};
                    for (long v : values) {
                        h.recordValue(v);
                    }
                    System.out.println(h.valuesAreEquivalent(h.getValueAtPercentile(10.0), 1));
                    System.out.println(h.valuesAreEquivalent(h.getValueAtPercentile(50.0), 10000));
                    System.out.println(h.valuesAreEquivalent(h.getValueAtPercentile(90.0), 100000000));
                    System.out.println(h.valuesAreEquivalent(h.getValueAtPercentile(100.0), 1000000000L));
                }
            }
        """)
        lines = run_java(code).split("\n")
        for i, line in enumerate(lines):
            assert line == "true", f"Percentile check {i} failed"


# ============================================================
# Test 25: Percentile round-trip consistency
# ============================================================
class TestPercentileConsistency:

    def test_percentile_round_trip(self):
        """getPercentileAtOrBelowValue(getValueAtPercentile(p)) should be >= p"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1, 10000000, 3);
                    for (int i = 1; i <= 10000; i++) {
                        h.recordValue(i);
                    }
                    int violations = 0;
                    for (double p = 1.0; p <= 100.0; p += 0.5) {
                        long val = h.getValueAtPercentile(p);
                        double actualPct = h.getPercentileAtOrBelowValue(val);
                        if (actualPct < p - 0.01) {
                            violations++;
                        }
                    }
                    System.out.println(violations);
                }
            }
        """)
        assert run_java(code) == "0"


# ============================================================
# Test 26: Cross-configuration histogram add
# ============================================================
class TestCrossConfigAdd:

    def test_add_different_ldv(self):
        """Adding histograms with different lowestDiscernibleValue uses value re-recording"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h1 = new HdrHistogram(1, 100000000L, 3);
                    HdrHistogram h2 = new HdrHistogram(1024, 100000000L, 3);
                    h1.recordValue(5000);
                    h2.recordValue(10240);
                    h2.recordValue(51200);
                    h1.add(h2);
                    System.out.println(h1.getTotalCount());
                    System.out.println(h1.valuesAreEquivalent(h1.getValueAtPercentile(50.0), 10240));
                    System.out.println(h1.getMinValue());
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "3"
        assert lines[1] == "true"
        assert lines[2] == "5000"


# ============================================================
# Test 27: ZigZag varint encoding
# ============================================================
class TestZigZagEncoding:

    def test_zigzag_values(self):
        """Verify ZigZag encoding maps correctly for known values"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    System.out.println(HistogramCodec.zigZagEncode(0));
                    System.out.println(HistogramCodec.zigZagEncode(-1));
                    System.out.println(HistogramCodec.zigZagEncode(1));
                    System.out.println(HistogramCodec.zigZagEncode(-2));
                    System.out.println(HistogramCodec.zigZagEncode(2));
                    System.out.println(HistogramCodec.zigZagDecode(0));
                    System.out.println(HistogramCodec.zigZagDecode(1));
                    System.out.println(HistogramCodec.zigZagDecode(2));
                    System.out.println(HistogramCodec.zigZagDecode(4));
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "0"
        assert lines[1] == "1"
        assert lines[2] == "2"
        assert lines[3] == "3"
        assert lines[4] == "4"
        assert lines[5] == "0"
        assert lines[6] == "-1"
        assert lines[7] == "1"
        assert lines[8] == "2"

    def test_zigzag_roundtrip(self):
        """zigZagDecode(zigZagEncode(n)) == n for a range of values"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    long[] values = {0, 1, -1, 127, -128, 1000000, -1000000,
                                     Long.MAX_VALUE, Long.MIN_VALUE};
                    int failures = 0;
                    for (long v : values) {
                        if (HistogramCodec.zigZagDecode(HistogramCodec.zigZagEncode(v)) != v) {
                            failures++;
                        }
                    }
                    System.out.println(failures);
                }
            }
        """)
        assert run_java(code) == "0"


# ============================================================
# Test 28: Codec round-trip with small histogram
# ============================================================
class TestCodecSmallRoundTrip:

    def test_small_histogram(self):
        """Encode/decode a small histogram and verify counts match"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    h.recordValue(100);
                    h.recordValue(200);
                    h.recordValue(1000);
                    String encoded = HistogramCodec.encode(h);
                    HdrHistogram decoded = HistogramCodec.decode(encoded);
                    System.out.println(decoded.getTotalCount());
                    System.out.println(decoded.getCountAtValue(100));
                    System.out.println(decoded.getCountAtValue(200));
                    System.out.println(decoded.getCountAtValue(1000));
                    System.out.println(decoded.getMinValue());
                    System.out.println(decoded.valuesAreEquivalent(decoded.getMaxValue(), 1000));
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "3"
        assert lines[1] == "1"
        assert lines[2] == "1"
        assert lines[3] == "1"
        assert lines[4] == "100"
        assert lines[5] == "true"


# ============================================================
# Test 29: Codec round-trip with large histogram
# ============================================================
class TestCodecLargeRoundTrip:

    def test_large_histogram(self):
        """Encode/decode histogram with many values across orders of magnitude"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1, Long.MAX_VALUE, 3);
                    long[] values = {1, 10, 100, 1000, 10000, 100000, 1000000};
                    for (long v : values) {
                        h.recordValueWithCount(v, 50);
                    }
                    String encoded = HistogramCodec.encode(h);
                    HdrHistogram decoded = HistogramCodec.decode(encoded);
                    System.out.println(decoded.getTotalCount());
                    boolean allMatch = true;
                    for (int i = 0; i < h.countsArrayLength; i++) {
                        if (h.counts[i] != decoded.counts[i]) {
                            allMatch = false;
                            break;
                        }
                    }
                    System.out.println(allMatch);
                    System.out.println(Math.abs(decoded.getMean() - h.getMean()) < 0.001);
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "350"
        assert lines[1] == "true"
        assert lines[2] == "true"


# ============================================================
# Test 30: Codec round-trip with empty histogram
# ============================================================
class TestCodecEmptyRoundTrip:

    def test_empty_histogram(self):
        """Encode/decode an empty histogram"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    String encoded = HistogramCodec.encode(h);
                    HdrHistogram decoded = HistogramCodec.decode(encoded);
                    System.out.println(decoded.getTotalCount());
                    System.out.println(decoded.getMinValue());
                    System.out.println(decoded.getMaxValue());
                }
            }
        """)
        lines = run_java(code).split("\n")
        assert lines[0] == "0"
        assert lines[1] == "0"
        assert lines[2] == "0"


# ============================================================
# Test 31: Codec determinism
# ============================================================
class TestCodecDeterminism:

    def test_deterministic_encoding(self):
        """Encoding the same histogram twice produces identical output"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(3600000000L, 3);
                    h.recordValue(42);
                    h.recordValue(84);
                    String e1 = HistogramCodec.encode(h);
                    String e2 = HistogramCodec.encode(h);
                    System.out.println(e1.equals(e2));
                }
            }
        """)
        assert run_java(code) == "true"


# ============================================================
# Test 32: Codec preserves percentiles
# ============================================================
class TestCodecPreservesPercentiles:

    def test_percentiles_match_after_roundtrip(self):
        """Decoded histogram must have identical percentile values"""
        code = textwrap.dedent("""\
            public class TestHdr {
                public static void main(String[] args) {
                    HdrHistogram h = new HdrHistogram(1, 100000000, 3);
                    for (int i = 1; i <= 10000; i++) {
                        h.recordValue(i);
                    }
                    String encoded = HistogramCodec.encode(h);
                    HdrHistogram decoded = HistogramCodec.decode(encoded);
                    int failures = 0;
                    for (double p = 1.0; p <= 100.0; p += 1.0) {
                        if (h.getValueAtPercentile(p) != decoded.getValueAtPercentile(p)) {
                            failures++;
                        }
                    }
                    System.out.println(failures);
                }
            }
        """)
        assert run_java(code) == "0"


# ============================================================
# Test 33: Makefile full pipeline (make clean + make all)
# THIS MUST BE THE LAST TEST CLASS — it runs make clean
# ============================================================
class TestMakefilePipeline:

    def test_make_clean_then_all(self):
        """Full pipeline: make clean && make all must succeed with ROUNDTRIP_OK"""
        subprocess.run(["make", "-C", "/app", "clean"],
                       capture_output=True, timeout=30)
        result = subprocess.run(["make", "-C", "/app", "all"],
                               capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, \
            f"make all failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert "ROUNDTRIP_OK" in result.stdout, \
            f"ROUNDTRIP_OK not in output: {result.stdout}"
