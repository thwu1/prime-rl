"""Fault localizer - maps CI errors to source code locations."""
import ast
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .parser import ErrorRecord


@dataclass
class OutlineNode:
    """Represents a node in the code structure outline."""
    kind: str  # 'class', 'func', 'import_block'
    name: str
    start: int  # 1-based line number
    end: int    # 1-based line number
    children: List['OutlineNode'] = field(default_factory=list)


@dataclass
class FaultLocation:
    """A localized fault in source code."""
    file_path: str
    line_range: Tuple[int, int]  # 1-based inclusive
    reason: str
    confidence: float
    outline_node: Optional[OutlineNode] = None


def build_outline(source_code: str) -> List[OutlineNode]:
    """Build a structural outline of Python source code using AST.

    Returns list of top-level OutlineNode objects representing classes,
    functions, and import blocks.
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    nodes: List[OutlineNode] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            children = []
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    children.append(OutlineNode(
                        kind='func',
                        name=child.name,
                        start=child.lineno,
                        end=child.end_lineno or child.lineno,
                    ))
            nodes.append(OutlineNode(
                kind='class',
                name=node.name,
                start=node.lineno,
                end=node.end_lineno or node.lineno,
                children=children,
            ))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nodes.append(OutlineNode(
                kind='func',
                name=node.name,
                start=node.lineno,
                end=node.end_lineno or node.lineno,
            ))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            nodes.append(OutlineNode(
                kind='import_block',
                name='imports',
                start=node.lineno,
                end=node.end_lineno or node.lineno,
            ))

    return nodes


def _extract_context_lines(
    source_lines: List[str],
    line_num: int,
    context: int = 3,
) -> str:
    """Extract lines around a target line number (1-based).

    Returns the context window as a single string with line numbers.
    """
    start = max(0, line_num - context)
    end = min(len(source_lines), line_num + context)
    return '\n'.join(
        f"{i + start + 1:4d}: {line}"
        for i, line in enumerate(source_lines[start:end])
    )


def find_enclosing_node(
    outline: List[OutlineNode],
    line_start: int,
    line_end: int,
) -> Optional[OutlineNode]:
    """Find the tightest enclosing outline node for a line range.

    Uses strict containment: node must fully contain [line_start, line_end].
    """
    best: Optional[OutlineNode] = None
    best_span = float('inf')

    def _search(nodes: List[OutlineNode]) -> None:
        nonlocal best, best_span
        for node in nodes:
            if node.start <= line_end and line_start <= node.end:  # intersection
                span = node.end - node.start
                if span < best_span:
                    best = node
                    best_span = span
                _search(node.children)

    _search(outline)
    return best


class BM25Scorer:
    """Simple BM25 scorer for ranking candidate files."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._corpus: List[List[str]] = []
        self._doc_lens: List[int] = []
        self._avgdl: float = 0.0
        self._doc_freqs: Dict[str, int] = {}
        self._n_docs: int = 0

    def fit(self, documents: List[str]) -> None:
        """Index a corpus of documents (file contents)."""
        self._corpus = [doc.lower().split() for doc in documents]
        self._n_docs = len(self._corpus)
        self._doc_lens = [len(doc) for doc in self._corpus]
        self._avgdl = sum(self._doc_lens) / max(1, self._n_docs)

        self._doc_freqs = {}
        for doc in self._corpus:
            seen = set(doc)
            for term in seen:
                self._doc_freqs[term] = self._doc_freqs.get(term, 0) + 1

    def _idf(self, term: str) -> float:
        """Compute inverse document frequency for a term."""
        df = self._doc_freqs.get(term, 0)
        return math.log((self._n_docs - df) / (df + 1e-10))

    def score(self, query: str, doc_idx: int) -> float:
        """Score a single document against a query."""
        query_terms = query.lower().split()
        doc = self._corpus[doc_idx]
        doc_len = self._doc_lens[doc_idx]

        total = 0.0
        term_freqs: Dict[str, int] = {}
        for term in doc:
            term_freqs[term] = term_freqs.get(term, 0) + 1

        for term in query_terms:
            if term not in term_freqs:
                continue
            tf = term_freqs[term]
            idf = self._idf(term)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self._avgdl)
            total += idf * numerator / denominator

        return total

    def rank_candidates(
        self,
        query: str,
        file_paths: List[str],
    ) -> list[dict[str, Any]]:
        """Rank files by BM25 relevance to a query.

        Returns:
            List of tuples (path, score, original_index),
            sorted by descending score.
        """
        if not self._corpus or not file_paths:
            return []

        scores: List[Tuple[str, float, int]] = []
        for idx, path in enumerate(file_paths):
            if idx < len(self._corpus):
                s = self.score(query, idx)
                scores.append((path, s, idx))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores


def localize_faults(
    errors: List[ErrorRecord],
    source_files: Dict[str, str],
) -> List[FaultLocation]:
    """Map error records to source code locations.

    Args:
        errors: List of ErrorRecord objects from log parsing.
        source_files: Dict mapping file paths to file contents.

    Returns:
        List of FaultLocation objects.
    """
    locations: List[FaultLocation] = []

    outlines: Dict[str, List[OutlineNode]] = {}
    for path, content in source_files.items():
        outlines[path] = build_outline(content)

    scorer = BM25Scorer()
    file_paths = list(source_files.keys())
    file_contents = [source_files[p] for p in file_paths]
    scorer.fit(file_contents)

    for error in errors:
        if error.file_path and error.file_path in source_files:
            content = source_files[error.file_path]
            source_lines = content.split('\n')
            line_num = error.line_number or 1
            outline = outlines.get(error.file_path, [])
            enclosing = find_enclosing_node(outline, line_num, line_num)

            if enclosing:
                location = FaultLocation(
                    file_path=error.file_path,
                    line_range=(enclosing.start, enclosing.end),
                    reason=error.message,
                    confidence=0.95,
                    outline_node=enclosing,
                )
            else:
                context_start = max(1, line_num - 3)
                context_end = min(len(source_lines), line_num + 3)
                location = FaultLocation(
                    file_path=error.file_path,
                    line_range=(context_start, context_end),
                    reason=error.message,
                    confidence=0.8,
                )
            locations.append(location)
        else:
            best_path: Optional[str] = None
            best_score = 0.0
            for idx, path in enumerate(file_paths):
                if idx < len(scorer._corpus):
                    s = scorer.score(error.message, idx)
                    if s > best_score:
                        best_score = s
                        best_path = path

            if best_path is not None and best_score > 0:
                locations.append(FaultLocation(
                    file_path=best_path,
                    line_range=(1, 10),
                    reason=f"BM25 match (score={best_score:.2f}): {error.message}",
                    confidence=min(0.7, best_score / 10),
                ))

    return locations
