
"""Fuzzy search module — Levenshtein automaton with bitpacking."""
import struct


class ParametricDFA:
    """Reusable fuzzy matching automaton for a given max edit distance.

    A single instance must produce correct results for any number of
    build_dfa() calls on different query strings.
    """

    def __init__(self, max_distance):
        raise NotImplementedError

    def build_dfa(self, query):
        """Build and return a ConcreteDFA for the given query string."""
        raise NotImplementedError


class ConcreteDFA:
    """A concrete DFA instantiated for a specific query string."""

    def __init__(self, parametric, query):
        raise NotImplementedError

    # initial_state (int): the start state

    def step(self, state, char):
        """Transition function; None = dead/sink state."""
        raise NotImplementedError

    def is_match(self, state):
        """Whether the state is accepting."""
        raise NotImplementedError

    def distance(self, state):
        """Minimum edit distance at this accepting state; -1 if non-accepting."""
        raise NotImplementedError


class FuzzySearcher:
    """Builds a search structure from a word list."""

    def __init__(self, words):
        raise NotImplementedError

    def search(self, parametric_dfa, query):
        """Returns a sorted list of (word, distance) tuples for all words within range."""
        raise NotImplementedError


def bitpack_postings(doc_ids):
    """Compress sorted integer doc ID lists. bitpack_postings([]) returns b""."""
    raise NotImplementedError


def unpack_postings(data):
    """Decompress bitpacked binary format. unpack_postings(b"") returns []."""
    raise NotImplementedError
