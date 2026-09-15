"""Tests for the BPE merge recovery task."""

import sys
import json
import pytest

sys.path.insert(0, '/app')
from tokenizer import encode, decode

with open('/app/test_cases.json') as f:
    test_cases = json.load(f)

with open('/app/metadata.json') as f:
    metadata = json.load(f)


class TestEncodeMatchesExpected:
    @pytest.mark.parametrize("idx", range(len(test_cases)))
    def test_encode(self, idx):
        case = test_cases[idx]
        result = encode(case['text'])
        assert result == case['expected_ids'], (
            f"encode({case['text']!r}) produced {result}, "
            f"expected {case['expected_ids']}"
        )


class TestDecodeProducesOriginal:
    @pytest.mark.parametrize("idx", range(len(test_cases)))
    def test_decode(self, idx):
        case = test_cases[idx]
        if not case['expected_ids']:
            result = decode([])
            assert result == "", f"decode([]) should return empty string, got {result!r}"
            return
        result = decode(case['expected_ids'])
        assert result == case['text'], (
            f"decode({case['expected_ids']}) produced {result!r}, "
            f"expected {case['text']!r}"
        )


class TestRoundtrip:
    @pytest.mark.parametrize("idx", range(len(test_cases)))
    def test_roundtrip_provided(self, idx):
        case = test_cases[idx]
        text = case['text']
        assert decode(encode(text)) == text, f"Roundtrip failed for {text!r}"

    additional_texts = [
        "Byte Pair Encoding is a data compression technique",
        "x = 42; y = x * 2 + 1",
        "   leading and trailing spaces   ",
        "UPPERCASE lowercase MiXeD",
        "Newlines\nare\nimportant\n",
        "Tabs\tand\tspaces mixed",
        "12345 67890 numbers",
        "a" * 100,
        "ab" * 50,
        "Short",
        " ",
        "  ",
        "The transformer architecture has revolutionized NLP.",
        "for i in range(10):\n    print(i)\n",
        "!@#$%^&*()",
    ]

    @pytest.mark.parametrize("text", additional_texts)
    def test_roundtrip_additional(self, text):
        assert decode(encode(text)) == text, f"Roundtrip failed for {text!r}"


class TestEdgeCases:
    def test_encode_empty(self):
        assert encode("") == []

    def test_decode_empty(self):
        assert decode([]) == ""

    def test_single_byte_tokens_in_range(self):
        """All token IDs should be within the expected vocabulary."""
        vocab_size = metadata['vocab_size']
        for case in test_cases:
            for tid in case['expected_ids']:
                assert 0 <= tid < vocab_size, (
                    f"Token ID {tid} out of range [0, {vocab_size}) "
                    f"in encoding of {case['text']!r}"
                )

    def test_encode_returns_list(self):
        result = encode("hello")
        assert isinstance(result, list), f"encode should return list, got {type(result)}"

    def test_decode_returns_str(self):
        ids = encode("hello")
        result = decode(ids)
        assert isinstance(result, str), f"decode should return str, got {type(result)}"

    def test_encode_deterministic(self):
        """Encoding the same string twice should give the same result."""
        text = "deterministic encoding test"
        assert encode(text) == encode(text)
