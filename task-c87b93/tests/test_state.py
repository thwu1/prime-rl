
import json
import subprocess
import pytest

CASCADE_SCRIPT = "/app/cascade.py"


def run_cascade(dom, css):
    """Write dom.json and styles.css, run cascade.py, return parsed JSON."""
    dom_path = "/app/_test_dom.json"
    css_path = "/app/_test_styles.css"
    with open(dom_path, "w") as f:
        json.dump(dom, f)
    with open(css_path, "w") as f:
        f.write(css)
    result = subprocess.run(
        ["python3", CASCADE_SCRIPT, dom_path, css_path],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"cascade.py failed:\n{result.stderr}"
    output = result.stdout.strip()
    assert output, "cascade.py produced no output"
    return json.loads(output)


# ===================================================================
# DOM fixtures
# ===================================================================

FLAT_DOM = {
    "tag": "html",
    "children": [{
        "tag": "body",
        "children": [{
            "tag": "div",
            "id": "box",
            "classes": ["container"],
            "children": [
                {
                    "tag": "p",
                    "id": "alpha",
                    "classes": ["text"],
                    "children": ["Hello"],
                },
                {
                    "tag": "p",
                    "classes": ["secondary", "text"],
                    "children": ["World"],
                },
            ],
        }],
    }],
}

DEEP_DOM = {
    "tag": "html",
    "children": [{
        "tag": "body",
        "children": [{
            "tag": "section",
            "id": "main",
            "children": [{
                "tag": "article",
                "classes": ["post"],
                "children": [
                    {
                        "tag": "h2",
                        "classes": ["title"],
                        "children": ["Title"],
                    },
                    {
                        "tag": "p",
                        "children": ["Content"],
                    },
                ],
            }],
        }],
    }],
}

# Path constants
P_ALPHA = "html > body > div#box > p#alpha"
P_BETA = "html > body > div#box > p.secondary.text"
DIV_BOX = "html > body > div#box"
SECTION = "html > body > section#main"
ARTICLE = "html > body > section#main > article.post"
H2_TITLE = "html > body > section#main > article.post > h2.title"
P_CONTENT = "html > body > section#main > article.post > p"


# ===================================================================
# 1. Backward-compatible cascade tests
# ===================================================================

class TestBasicCascade:

    def test_specificity_ordering(self):
        css = """
        p { color: blue; }
        .text { color: red; }
        #alpha { color: green; }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "green"

    def test_important_beats_specificity(self):
        css = """
        #alpha { color: green; }
        p { color: red !important; }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "red"

    def test_where_zero_specificity(self):
        css = """
        :where(#alpha) { color: red; }
        p { color: blue; }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "blue"

    def test_source_order_tiebreak(self):
        css = """
        .text { color: red; }
        .text { color: blue; }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "blue"


# ===================================================================
# 2. Custom properties — var() substitution
# ===================================================================

class TestCustomProperties:

    def test_basic_var(self):
        css = "p { --text-color: red; color: var(--text-color); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "red"

    def test_var_fallback(self):
        css = "p { color: var(--undefined, blue); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "blue"

    def test_var_nested_fallback(self):
        css = "p { --backup: green; color: var(--missing, var(--backup)); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "green"

    def test_var_chain(self):
        css = "p { --a: navy; --b: var(--a); color: var(--b); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "navy"

    def test_var_in_compound_value(self):
        css = "p { --gap: 10px; margin: var(--gap) 0; }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["margin"] == "10px 0"

    def test_custom_props_excluded_from_output(self):
        css = "p { --x: hello; color: var(--x); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "hello"
        assert "--x" not in result[P_ALPHA]


# ===================================================================
# 3. Cycle detection
# ===================================================================

class TestCycleDetection:

    def test_self_referencing(self):
        css = "p { --a: var(--a); color: var(--a, fallback); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "fallback"

    def test_mutual_cycle(self):
        css = "p { --a: var(--b); --b: var(--a); color: var(--a, cycled); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "cycled"

    def test_three_way_cycle(self):
        css = """
        p { --x: var(--y); --y: var(--z); --z: var(--x);
            color: var(--x, triple); }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "triple"

    def test_cycle_no_fallback_drops_property(self):
        css = "p { --a: var(--a); color: var(--a); }"
        result = run_cascade(FLAT_DOM, css)
        p_props = result.get(P_ALPHA, {})
        assert p_props.get("color", "") == ""

    def test_long_chain_no_cycle(self):
        css = """
        p { --a: hello; --b: var(--a); --c: var(--b);
            --d: var(--c); color: var(--d); }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "hello"


# ===================================================================
# 4. Inheritance
# ===================================================================

class TestInheritance:

    def test_color_inherits_to_child(self):
        css = "div#box { color: red; }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "red"

    def test_margin_does_not_inherit(self):
        css = "div#box { margin: 10px; }"
        result = run_cascade(FLAT_DOM, css)
        p_props = result.get(P_ALPHA, {})
        assert "margin" not in p_props

    def test_custom_property_inherits(self):
        css = """
        div#box { --theme: dark; }
        p { color: var(--theme); }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "dark"

    def test_deep_inheritance_chain(self):
        css = "body { color: purple; }"
        result = run_cascade(DEEP_DOM, css)
        assert result[P_CONTENT]["color"] == "purple"

    def test_inherit_keyword_non_inherited(self):
        css = """
        div#box { margin: 20px; }
        p { margin: inherit; }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["margin"] == "20px"

    def test_initial_keyword_blocks_inheritance(self):
        css = """
        body { color: red; }
        article { color: initial; }
        """
        result = run_cascade(DEEP_DOM, css)
        art_props = result.get(ARTICLE, {})
        assert art_props.get("color", "") == ""
        # Children of article should also NOT have color (nothing to inherit)
        p_props = result.get(P_CONTENT, {})
        assert p_props.get("color", "") == ""

    def test_child_overrides_inherited(self):
        css = """
        body { color: red; }
        p { color: blue; }
        """
        result = run_cascade(DEEP_DOM, css)
        assert result[P_CONTENT]["color"] == "blue"


# ===================================================================
# 5. calc() evaluation
# ===================================================================

class TestCalcEvaluation:

    def test_addition(self):
        css = "p { width: calc(10px + 20px); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "30px"

    def test_subtraction(self):
        css = "p { width: calc(100px - 30px); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "70px"

    def test_multiplication(self):
        css = "p { width: calc(3 * 10px); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "30px"

    def test_division(self):
        css = "p { width: calc(100px / 4); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "25px"

    def test_nested_calc(self):
        css = "p { width: calc(calc(10px + 5px) * 2); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "30px"

    def test_operator_precedence(self):
        css = "p { width: calc(10px + 5px * 2); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "20px"


# ===================================================================
# 6. min() / max() / clamp()
# ===================================================================

class TestMinMaxClamp:

    def test_min_function(self):
        css = "p { width: min(30px, 10px, 20px); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "10px"

    def test_max_function(self):
        css = "p { width: max(30px, 10px, 20px); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "30px"

    def test_clamp_below_range(self):
        css = "p { width: clamp(10px, 5px, 30px); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "10px"

    def test_clamp_in_range(self):
        css = "p { width: clamp(10px, 20px, 30px); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "20px"

    def test_clamp_above_range(self):
        css = "p { width: clamp(10px, 50px, 30px); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "30px"


# ===================================================================
# 7. Integration — features interacting
# ===================================================================

class TestIntegration:

    def test_var_with_calc_value(self):
        css = "p { --gap: calc(10px + 5px); margin: var(--gap); }"
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["margin"] == "15px"

    def test_inherited_custom_prop_with_var(self):
        css = """
        div#box { --col-width: calc(100px / 2); }
        p { width: var(--col-width); }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "50px"

    def test_cascade_specificity_custom_props(self):
        css = """
        p { --x: low; }
        #alpha { --x: high; }
        p { color: var(--x); }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "high"

    def test_full_pipeline_var_calc_inherit(self):
        css = """
        body { --base: 8px; color: navy; }
        div#box { --scale: 3; }
        p { width: calc(var(--base) * var(--scale)); }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["width"] == "24px"
        assert result[P_ALPHA]["color"] == "navy"

    def test_var_fallback_chain_with_inheritance(self):
        css = """
        body { --primary: teal; }
        p { color: var(--accent, var(--primary)); }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "teal"

    def test_inherited_custom_prop_cycle_fallback(self):
        css = """
        body { --a: var(--b); --b: var(--a); }
        p { color: var(--a, safe); }
        """
        result = run_cascade(FLAT_DOM, css)
        assert result[P_ALPHA]["color"] == "safe"
