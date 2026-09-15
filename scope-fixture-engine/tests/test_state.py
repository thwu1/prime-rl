
import sys
import os
import glob
import pytest

sys.path.insert(0, "/app")


class TestParseFixture:
    """Test that parse_fixture correctly extracts structured scope data."""

    def _load(self, name):
        path = f"/app/fixtures/{name}.scope"
        with open(path, "r") as f:
            return f.read()

    def test_module_importable(self):
        import scope_engine
        assert hasattr(scope_engine, "parse_fixture")
        assert hasattr(scope_engine, "render_fixture")
        assert hasattr(scope_engine, "map_captures_to_scopes")
        assert hasattr(scope_engine, "annotate_source")

    def test_parse_returns_list(self):
        from scope_engine import parse_fixture
        text = self._load("statement_simple")
        result = parse_fixture(text)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_parse_simple_statement_ranges(self):
        from scope_engine import parse_fixture
        text = self._load("statement_simple")
        scopes = parse_fixture(text)
        scope = scopes[0]
        # Content, Removal, and Domain all equal 0:0-0:16
        for facet in ["Content", "Removal", "Domain"]:
            r = scope.ranges[facet]
            assert r.start_line == 0
            assert r.start_col == 0
            assert r.end_line == 0
            assert r.end_col == 16
        assert scope.insertion_delimiter == "\n"

    def test_parse_multiline_ranges(self):
        from scope_engine import parse_fixture
        text = self._load("statement_multiline")
        scopes = parse_fixture(text)
        scope = scopes[0]
        r = scope.ranges["Domain"]
        assert r.start_line == 0
        assert r.start_col == 0
        assert r.end_line == 2
        assert r.end_col == 1

    def test_parse_multiple_scopes(self):
        from scope_engine import parse_fixture
        text = self._load("argument_multiple")
        scopes = parse_fixture(text)
        assert len(scopes) == 2
        # First argument: 0:4-0:7
        r0 = scopes[0].ranges["Removal"]
        assert r0.start_col == 4
        assert r0.end_col == 7
        # Second argument: 0:9-0:12
        r1 = scopes[1].ranges["Removal"]
        assert r1.start_col == 9
        assert r1.end_col == 12
        assert scopes[0].insertion_delimiter == ", "
        assert scopes[1].insertion_delimiter == ", "

    def test_parse_empty_range(self):
        from scope_engine import parse_fixture
        text = self._load("class_interior")
        scopes = parse_fixture(text)
        assert len(scopes) == 2
        # Second scope is Interior with empty range 0:11-0:11
        interior_scope = scopes[1]
        r = interior_scope.ranges["Interior"]
        assert r.start_line == 0
        assert r.start_col == 11
        assert r.end_line == 0
        assert r.end_col == 11

    def test_parse_different_content_removal_domain(self):
        from scope_engine import parse_fixture
        text = self._load("argument_formal")
        scopes = parse_fixture(text)
        assert len(scopes) == 2
        s = scopes[0]
        # Content and Removal and Domain are all different
        assert s.ranges["Content"].start_col == 9
        assert s.ranges["Content"].end_col == 16
        assert s.ranges["Removal"].start_col == 9
        assert s.ranges["Removal"].end_col == 18
        assert s.ranges["Domain"].start_col == 8
        assert s.ranges["Domain"].end_col == 26

    def test_parse_method_in_class_multiline_domain(self):
        from scope_engine import parse_fixture
        text = self._load("method_in_class")
        scopes = parse_fixture(text)
        assert len(scopes) == 1
        s = scopes[0]
        # Content is on line 1
        assert s.ranges["Content"].start_line == 1
        assert s.ranges["Content"].end_line == 1
        # Domain spans all 3 lines
        assert s.ranges["Domain"].start_line == 0
        assert s.ranges["Domain"].end_line == 2
        assert s.ranges["Domain"].end_col == 1

    def test_parse_if_statement_multiline(self):
        from scope_engine import parse_fixture
        text = self._load("if_statement")
        scopes = parse_fixture(text)
        assert len(scopes) == 1
        s = scopes[0]
        assert s.ranges["Domain"].start_line == 0
        assert s.ranges["Domain"].end_line == 2
        assert s.ranges["Domain"].end_col == 6

    def test_parse_iteration_scope(self):
        from scope_engine import parse_fixture
        text = self._load("statement_iteration")
        scopes = parse_fixture(text)
        assert len(scopes) == 2
        # First statement: Removal 0:0-0:12, Domain 0:0-1:12
        s0 = scopes[0]
        assert s0.ranges["Removal"].start_line == 0
        assert s0.ranges["Removal"].end_col == 12
        assert s0.ranges["Domain"].end_line == 1
        # Second statement: Removal 1:0-1:12
        s1 = scopes[1]
        assert s1.ranges["Removal"].start_line == 1
        assert s1.ranges["Removal"].end_col == 12


class TestRenderFixture:
    """Test that render_fixture produces correct visual output."""

    def _load(self, name):
        path = f"/app/fixtures/{name}.scope"
        with open(path, "r") as f:
            return f.read()

    def test_render_simple_statement(self):
        from scope_engine import parse_fixture, render_fixture
        text = self._load("statement_simple")
        source = text.split("---")[0].rstrip("\n")
        scopes = parse_fixture(text)
        rendered = render_fixture(source, scopes)
        assert rendered == text

    def test_render_multiline(self):
        from scope_engine import parse_fixture, render_fixture
        text = self._load("statement_multiline")
        source = text.split("---")[0].rstrip("\n")
        scopes = parse_fixture(text)
        rendered = render_fixture(source, scopes)
        assert rendered == text

    def test_render_multiple_scopes(self):
        from scope_engine import parse_fixture, render_fixture
        text = self._load("argument_multiple")
        source = text.split("---")[0].rstrip("\n")
        scopes = parse_fixture(text)
        rendered = render_fixture(source, scopes)
        assert rendered == text

    def test_render_empty_range(self):
        from scope_engine import parse_fixture, render_fixture
        text = self._load("class_interior")
        source = text.split("---")[0].rstrip("\n")
        scopes = parse_fixture(text)
        rendered = render_fixture(source, scopes)
        assert rendered == text

    def test_render_different_facet_ranges(self):
        from scope_engine import parse_fixture, render_fixture
        text = self._load("argument_formal")
        source = text.split("---")[0].rstrip("\n")
        scopes = parse_fixture(text)
        rendered = render_fixture(source, scopes)
        assert rendered == text


class TestRoundTrip:
    """Test byte-for-byte round-trip fidelity on all fixture files."""

    @pytest.fixture(params=sorted(glob.glob("/app/fixtures/*.scope")))
    def fixture_path(self, request):
        return request.param

    def test_roundtrip(self, fixture_path):
        from scope_engine import parse_fixture, render_fixture
        with open(fixture_path, "r") as f:
            original = f.read()
        source = original.split("---")[0].rstrip("\n")
        scopes = parse_fixture(original)
        rendered = render_fixture(source, scopes)
        if rendered != original:
            # Show detailed diff for debugging
            orig_lines = original.splitlines(keepends=True)
            rend_lines = rendered.splitlines(keepends=True)
            for i, (o, r) in enumerate(zip(orig_lines, rend_lines)):
                if o != r:
                    pytest.fail(
                        f"Mismatch at line {i+1} in {os.path.basename(fixture_path)}:\n"
                        f"  expected: {o!r}\n"
                        f"  got:      {r!r}"
                    )
            if len(orig_lines) != len(rend_lines):
                pytest.fail(
                    f"Line count mismatch in {os.path.basename(fixture_path)}: "
                    f"expected {len(orig_lines)}, got {len(rend_lines)}"
                )
            pytest.fail(f"Unknown mismatch in {os.path.basename(fixture_path)}")


class TestMapCaptures:
    """Test the capture-to-scope mapper."""

    def test_basic_mapping(self):
        from scope_engine import map_captures_to_scopes, Range
        captures = [
            ("namedFunction", (0, 0), (2, 1)),
            ("namedFunction.domain", (0, 0), (5, 0)),
            ("namedFunction.interior", (1, 0), (1, 20)),
        ]
        scopes = map_captures_to_scopes(captures, insertion_delimiter="\n")
        assert len(scopes) == 1
        s = scopes[0]
        assert s.ranges["Content"] == Range(0, 0, 2, 1)
        assert s.ranges["Domain"] == Range(0, 0, 5, 0)
        assert s.ranges["Interior"] == Range(1, 0, 1, 20)

    def test_removal_derived_from_content(self):
        """When no explicit removal, Removal == Content."""
        from scope_engine import map_captures_to_scopes, Range
        captures = [
            ("statement", (0, 0), (0, 16)),
        ]
        scopes = map_captures_to_scopes(captures, insertion_delimiter="\n")
        s = scopes[0]
        assert s.ranges["Removal"] == Range(0, 0, 0, 16)
        assert s.ranges["Content"] == Range(0, 0, 0, 16)

    def test_removal_derived_from_leading_trailing(self):
        """Removal = union of Leading + Content + Trailing."""
        from scope_engine import map_captures_to_scopes, Range
        captures = [
            ("collectionItem", (0, 5), (0, 10)),
            ("collectionItem.leading", (0, 3), (0, 5)),
            ("collectionItem.trailing", (0, 10), (0, 12)),
        ]
        scopes = map_captures_to_scopes(captures, insertion_delimiter=", ")
        s = scopes[0]
        assert s.ranges["Content"] == Range(0, 5, 0, 10)
        assert s.ranges["Leading"] == Range(0, 3, 0, 5)
        assert s.ranges["Trailing"] == Range(0, 10, 0, 12)
        # Removal spans from start of leading to end of trailing
        assert s.ranges["Removal"] == Range(0, 3, 0, 12)

    def test_domain_defaults_to_removal(self):
        """When no explicit domain, Domain == Removal."""
        from scope_engine import map_captures_to_scopes, Range
        captures = [
            ("statement", (0, 0), (0, 16)),
        ]
        scopes = map_captures_to_scopes(captures, insertion_delimiter="\n")
        s = scopes[0]
        assert s.ranges["Domain"] == Range(0, 0, 0, 16)

    def test_multiple_scope_groups(self):
        """Multiple distinct scope names produce separate scope objects."""
        from scope_engine import map_captures_to_scopes
        captures = [
            ("argument", (0, 4), (0, 7)),
            ("argument", (0, 9), (0, 12)),
        ]
        scopes = map_captures_to_scopes(captures, insertion_delimiter=", ")
        assert len(scopes) == 2

    def test_leading_only_removal(self):
        """Leading without trailing still extends removal."""
        from scope_engine import map_captures_to_scopes, Range
        captures = [
            ("decorator", (1, 0), (1, 10)),
            ("decorator.leading", (0, 0), (1, 0)),
        ]
        scopes = map_captures_to_scopes(captures, insertion_delimiter="\n")
        s = scopes[0]
        assert s.ranges["Removal"] == Range(0, 0, 1, 10)

    def test_explicit_removal_overrides(self):
        """Explicit @name.removal overrides the derived one."""
        from scope_engine import map_captures_to_scopes, Range
        captures = [
            ("item", (0, 5), (0, 10)),
            ("item.removal", (0, 3), (0, 15)),
        ]
        scopes = map_captures_to_scopes(captures, insertion_delimiter=", ")
        s = scopes[0]
        assert s.ranges["Removal"] == Range(0, 3, 0, 15)


class TestRangeObject:
    """Test Range data class properties."""

    def test_range_equality(self):
        from scope_engine import Range
        r1 = Range(0, 0, 0, 16)
        r2 = Range(0, 0, 0, 16)
        assert r1 == r2

    def test_range_inequality(self):
        from scope_engine import Range
        r1 = Range(0, 0, 0, 16)
        r2 = Range(0, 0, 0, 17)
        assert r1 != r2

    def test_range_fields(self):
        from scope_engine import Range
        r = Range(1, 5, 3, 10)
        assert r.start_line == 1
        assert r.start_col == 5
        assert r.end_line == 3
        assert r.end_col == 10


class TestScopeObject:
    """Test Scope data class properties."""

    def test_scope_has_ranges_dict(self):
        from scope_engine import parse_fixture
        text = open("/app/fixtures/statement_simple.scope").read()
        scopes = parse_fixture(text)
        assert isinstance(scopes[0].ranges, dict)

    def test_scope_has_insertion_delimiter(self):
        from scope_engine import parse_fixture
        text = open("/app/fixtures/statement_simple.scope").read()
        scopes = parse_fixture(text)
        assert isinstance(scopes[0].insertion_delimiter, str)


class TestEdgeCases:
    """Test edge cases in rendering."""

    def test_single_char_range_visualization(self):
        """A 1-char range should render as >-<"""
        from scope_engine import render_fixture, Scope, Range
        source = "x"
        scope = Scope(
            ranges={"Content": Range(0, 0, 0, 1), "Removal": Range(0, 0, 0, 1), "Domain": Range(0, 0, 0, 1)},
            insertion_delimiter="\n"
        )
        rendered = render_fixture(source, [scope])
        lines = rendered.split("\n")
        # Find the visual line
        visual_lines = [l for l in lines if ">" in l and "<" in l and "|" not in l]
        assert len(visual_lines) >= 1
        # The visual marker should be >-<
        assert ">-<" in visual_lines[0]

    def test_empty_range_visualization(self):
        """An empty range (start == end) should render as ><"""
        from scope_engine import render_fixture, Scope, Range
        source = "ab"
        scope = Scope(
            ranges={"Interior": Range(0, 1, 0, 1)},
            insertion_delimiter="\n"
        )
        rendered = render_fixture(source, [scope])
        lines = rendered.split("\n")
        visual_lines = [l for l in lines if ">" in l and "<" in l and "|" not in l]
        assert len(visual_lines) >= 1
        assert "><" in visual_lines[0]

    def test_line_number_padding(self):
        """Line numbers should be space-padded to consistent width."""
        from scope_engine import parse_fixture
        text = open("/app/fixtures/method_in_class.scope").read()
        scopes = parse_fixture(text)
        # The Domain range spans lines 0-2, so line numbers should be single digit
        # Check re-render preserves this
        from scope_engine import render_fixture
        source = text.split("---")[0].rstrip("\n")
        rendered = render_fixture(source, scopes)
        assert rendered == text


class TestTreeSitterPipeline:
    """Test end-to-end tree-sitter scope annotation pipeline."""

    @pytest.fixture(autouse=True)
    def setup_language(self):
        try:
            import tree_sitter_python as tspython
            from tree_sitter import Language
            self.py_lang = Language(tspython.language())
        except Exception as e:
            pytest.skip(f"tree-sitter-python not available: {e}")

    def test_annotate_expression_statement(self):
        """Annotate a simple expression statement and verify scope output."""
        from scope_engine import annotate_source, parse_fixture

        source = "x = 1"
        query = "(expression_statement) @statement"

        output = annotate_source(source, self.py_lang, query)
        assert "---" in output
        assert source in output

        scopes = parse_fixture(output)
        assert len(scopes) >= 1
        s = scopes[0]
        assert "Content" in s.ranges
        assert s.ranges["Content"].start_line == 0
        assert s.ranges["Content"].start_col == 0
        # Derived ranges should exist
        assert "Removal" in s.ranges
        assert "Domain" in s.ranges
        # Without leading/trailing, all three should be equal
        assert s.ranges["Content"] == s.ranges["Removal"]
        assert s.ranges["Removal"] == s.ranges["Domain"]

    def test_annotate_function_with_interior(self):
        """Annotate a function definition using query that captures interior."""
        from scope_engine import annotate_source, parse_fixture

        source = "def foo():\n    pass"
        query_text = open("/app/queries/python_function.scm").read()

        output = annotate_source(source, self.py_lang, query_text)
        scopes = parse_fixture(output)

        assert len(scopes) == 1
        s = scopes[0]
        assert "Content" in s.ranges
        assert "Interior" in s.ranges
        assert "Removal" in s.ranges
        assert "Domain" in s.ranges

        # Content should be the full function definition starting at (0,0)
        assert s.ranges["Content"].start_line == 0
        assert s.ranges["Content"].start_col == 0

        # Interior should be strictly within Content
        c = s.ranges["Content"]
        i = s.ranges["Interior"]
        assert (i.start_line, i.start_col) >= (c.start_line, c.start_col)
        assert (i.end_line, i.end_col) <= (c.end_line, c.end_col)
        # Interior should not equal Content (it's the body, not the whole func)
        assert i != c

    def test_annotate_multiple_functions(self):
        """Multiple function definitions produce multiple scopes."""
        from scope_engine import annotate_source, parse_fixture

        source = "def foo():\n    pass\n\ndef bar():\n    return 1"
        query_text = open("/app/queries/python_function.scm").read()

        output = annotate_source(source, self.py_lang, query_text)
        scopes = parse_fixture(output)

        assert len(scopes) == 2
        # First function starts at line 0
        assert scopes[0].ranges["Content"].start_line == 0
        # Second function starts at line 3
        assert scopes[1].ranges["Content"].start_line == 3
        # Both should have Interior
        assert "Interior" in scopes[0].ranges
        assert "Interior" in scopes[1].ranges

    def test_annotate_class_with_interior(self):
        """Annotate a class definition with interior scope."""
        from scope_engine import annotate_source, parse_fixture

        source = "class Foo:\n    x = 1"
        query_text = open("/app/queries/python_class.scm").read()

        output = annotate_source(source, self.py_lang, query_text)
        scopes = parse_fixture(output)

        assert len(scopes) >= 1
        s = scopes[0]
        assert "Content" in s.ranges
        assert "Interior" in s.ranges
        assert s.ranges["Content"].start_line == 0
        assert s.ranges["Content"].start_col == 0

    def test_annotation_output_roundtrips(self):
        """Output from annotate_source should survive parse/render round-trip."""
        from scope_engine import annotate_source, parse_fixture, render_fixture

        source = "x = 1\ny = 2"
        query = "(expression_statement) @statement"

        output = annotate_source(source, self.py_lang, query)
        parsed_source = output.split("---")[0].rstrip("\n")
        scopes = parse_fixture(output)
        re_rendered = render_fixture(parsed_source, scopes)
        assert re_rendered == output

    def test_annotate_with_query_file(self):
        """Annotation using a .scm file from /app/queries/ works correctly."""
        from scope_engine import annotate_source, parse_fixture

        source = "def greet(name):\n    print(name)"
        query_text = open("/app/queries/python_function.scm").read()

        output = annotate_source(source, self.py_lang, query_text)
        scopes = parse_fixture(output)

        assert len(scopes) >= 1
        s = scopes[0]
        assert "Content" in s.ranges
        assert "Interior" in s.ranges
        assert s.insertion_delimiter == "\n"

    def test_annotate_multistatement(self):
        """Multiple statements in source produce multiple scopes."""
        from scope_engine import annotate_source, parse_fixture

        source = "x = 1\nimport os"
        query_text = open("/app/queries/python_statement.scm").read()

        output = annotate_source(source, self.py_lang, query_text)
        scopes = parse_fixture(output)

        assert len(scopes) == 2
        assert scopes[0].ranges["Content"].start_line == 0
        assert scopes[1].ranges["Content"].start_line == 1
