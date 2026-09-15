"""Basic unit tests for the compact codec."""

import math
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from compact import encode, decode


class TestNone(unittest.TestCase):
    def test_roundtrip(self):
        self.assertIsNone(decode(encode(None)))


class TestBool(unittest.TestCase):
    def test_true(self):
        self.assertIs(decode(encode(True)), True)

    def test_false(self):
        self.assertIs(decode(encode(False)), False)


class TestInt(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(decode(encode(0)), 0)

    def test_positive(self):
        for n in [1, 42, 127, 128, 255, 256, 1000, 65535, 100000]:
            self.assertEqual(decode(encode(n)), n)

    def test_negative(self):
        for n in [-1, -42, -128, -129, -256, -1000, -65536]:
            self.assertEqual(decode(encode(n)), n)

    def test_range(self):
        for n in range(-100, 101):
            self.assertEqual(decode(encode(n)), n)


class TestFloat(unittest.TestCase):
    def test_regular(self):
        for f in [1.0, -1.0, 3.14159, -2.71828, 1e10, 1e-10, 1e100]:
            self.assertEqual(decode(encode(f)), f)

    def test_zero(self):
        self.assertEqual(decode(encode(0.0)), 0.0)

    def test_inf(self):
        self.assertEqual(decode(encode(float('inf'))), float('inf'))
        self.assertEqual(decode(encode(float('-inf'))), float('-inf'))

    def test_nan(self):
        result = decode(encode(float('nan')))
        self.assertTrue(math.isnan(result))


class TestString(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(decode(encode("")), "")

    def test_ascii(self):
        self.assertEqual(decode(encode("hello")), "hello")
        self.assertEqual(decode(encode("hello world")), "hello world")

    def test_longer(self):
        s = "a" * 300
        self.assertEqual(decode(encode(s)), s)


class TestBytes(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(decode(encode(b"")), b"")

    def test_values(self):
        self.assertEqual(decode(encode(b"\x00\x01\x02")), b"\x00\x01\x02")
        self.assertEqual(decode(encode(b"hello")), b"hello")

    def test_all_byte_values(self):
        data = bytes(range(256))
        self.assertEqual(decode(encode(data)), data)


class TestList(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(decode(encode([])), [])

    def test_ints(self):
        self.assertEqual(decode(encode([1, 2, 3])), [1, 2, 3])

    def test_strings(self):
        self.assertEqual(decode(encode(["a", "b", "c"])), ["a", "b", "c"])

    def test_mixed(self):
        self.assertEqual(
            decode(encode([1, "two", 3.0, None, True])),
            [1, "two", 3.0, None, True],
        )


class TestDict(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(decode(encode({})), {})

    def test_simple(self):
        self.assertEqual(decode(encode({"a": 1})), {"a": 1})
        self.assertEqual(decode(encode({"key": "value"})), {"key": "value"})

    def test_multiple_keys(self):
        d = {"x": 1, "y": 2, "z": 3}
        self.assertEqual(decode(encode(d)), d)


class TestTuple(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(decode(encode(())), ())

    def test_single_none(self):
        self.assertEqual(decode(encode((None,))), (None,))

    def test_bools(self):
        self.assertEqual(decode(encode((True, False))), (True, False))

    def test_multiple_none(self):
        self.assertEqual(decode(encode((None, None, None))), (None, None, None))


class TestNested(unittest.TestCase):
    def test_list_of_lists(self):
        self.assertEqual(decode(encode([[1, 2], [3, 4]])), [[1, 2], [3, 4]])

    def test_dict_with_list(self):
        d = {"name": "test", "values": [1, 2, 3], "active": True}
        self.assertEqual(decode(encode(d)), d)

    def test_list_of_dicts(self):
        data = [{"a": 1}, {"b": 2}]
        self.assertEqual(decode(encode(data)), data)


class TestErrors(unittest.TestCase):
    def test_unsupported_type(self):
        with self.assertRaises(TypeError):
            encode(set())

    def test_non_string_key(self):
        with self.assertRaises(TypeError):
            encode({1: "value"})

    def test_empty_data(self):
        with self.assertRaises(ValueError):
            decode(b"")

    def test_bad_tag(self):
        with self.assertRaises(ValueError):
            decode(b"\xff")


if __name__ == "__main__":
    unittest.main()
