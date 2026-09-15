
import sys
sys.path.insert(0, "/app")

import pytest
from screen_reader import VirtualScreenReader


# ════════════════════════════════════════════════════
# Inline HTML fixtures
# ════════════════════════════════════════════════════

BASIC_HTML = """\
<body>
  <nav aria-label="Main">
    <a href="/home">Home</a>
    <a href="/about">About</a>
  </nav>
  <main>
    <h1>Title</h1>
    <h2>Subtitle</h2>
    <button>Click</button>
  </main>
  <footer>
    <button>Footer Action</button>
  </footer>
</body>
"""

OWNS_HTML = """\
<body>
  <div role="tablist" aria-label="Settings" aria-owns="tab3">
    <div role="tab" id="tab1">General</div>
    <div role="tab" id="tab2">Advanced</div>
  </div>
  <main>
    <h1>Content</h1>
  </main>
  <div role="tab" id="tab3">Expert</div>
</body>
"""

OWNS_CIRCULAR_HTML = """\
<body>
  <div id="grp-a" role="group" aria-label="Group A" aria-owns="grp-b">
    <button>In A</button>
  </div>
  <div id="grp-b" role="group" aria-label="Group B" aria-owns="grp-a">
    <button>In B</button>
  </div>
</body>
"""

OWNS_HIDDEN_HTML = """\
<body>
  <div role="tablist" aria-label="Tabs" aria-owns="hidden-tab">
    <div role="tab" id="t1">Visible Tab</div>
  </div>
  <div role="tab" id="hidden-tab" aria-hidden="true">Hidden Tab</div>
</body>
"""

PRES_TABLE_HTML = """\
<body>
  <main>
    <table role="presentation">
      <tr>
        <td>Name</td>
        <td>Alice</td>
      </tr>
      <tr>
        <td>Role</td>
        <td>Engineer</td>
      </tr>
    </table>
  </main>
</body>
"""

PRES_LIST_HTML = """\
<body>
  <main>
    <ul role="none">
      <li>Alpha</li>
      <li>Beta</li>
      <li>Gamma</li>
    </ul>
  </main>
</body>
"""

PRES_EXPLICIT_HTML = """\
<body>
  <main>
    <table role="presentation">
      <tr>
        <td>Text</td>
        <td role="button">Action</td>
      </tr>
    </table>
  </main>
</body>
"""

VALUE_HTML = """\
<body>
  <main>
    <div role="slider" aria-label="Volume" aria-valuenow="50" aria-valuemin="0" aria-valuemax="100"></div>
    <div role="slider" aria-label="Speed" aria-valuetext="Medium" aria-valuenow="5"></div>
    <div role="progressbar" aria-label="Upload" aria-valuenow="75"></div>
  </main>
</body>
"""

EMBEDDED_CTRL_HTML = """\
<body>
  <main>
    <div id="speed-lbl">Speed <input type="range" aria-valuenow="5" aria-valuemin="1" aria-valuemax="10" /></div>
    <div role="group" aria-labelledby="speed-lbl">
      <button>Apply</button>
    </div>
  </main>
</body>
"""

FLOWTO_HTML = """\
<body>
  <section aria-label="Intro" id="sec1" aria-flowto="sec3">
    <h1>Introduction</h1>
  </section>
  <section aria-label="Details" id="sec2">
    <h2>Details</h2>
  </section>
  <section aria-label="Summary" id="sec3" aria-flowto="sec2">
    <h2>Summary</h2>
  </section>
</body>
"""

HIDDEN_HTML = """\
<body>
  <main>
    <h1>Visible</h1>
    <div aria-hidden="true">
      <button>Hidden</button>
    </div>
    <span hidden>
      <button>Also Hidden</button>
    </span>
    <button>Active</button>
  </main>
</body>
"""

MODAL_HTML = """\
<body>
  <main>
    <h1>Background</h1>
    <button>Background Btn</button>
  </main>
  <div role="dialog" aria-modal="true" aria-label="Confirm">
    <h2>Sure?</h2>
    <button>Yes</button>
    <button>No</button>
  </div>
</body>
"""

INERT_HTML = """\
<body>
  <div inert>
    <h1>Inert Heading</h1>
    <button>Inert Button</button>
  </div>
  <main>
    <h2>Active Content</h2>
    <button>Active Button</button>
  </main>
</body>
"""

NAMING_HTML = """\
<body>
  <main>
    <h1 id="title">Dashboard</h1>
    <nav aria-labelledby="title">
      <a href="/" aria-label="Go home">Home</a>
    </nav>
    <section aria-label="Profile">
      <h2>Your Profile</h2>
      <img src="avatar.png" alt="User avatar" />
      <input type="text" aria-label="Username" />
    </section>
    <button aria-describedby="hint">Save</button>
    <span id="hint">Saves changes</span>
  </main>
</body>
"""


# ════════════════════════════════════════════════════
# Helper
# ════════════════════════════════════════════════════

def collect_all_phrases(sr, html):
    """Start and collect all phrases via next() until wrap."""
    first = sr.start(html)
    phrases = [first]
    while True:
        p = sr.next()
        if p == first:
            break
        phrases.append(p)
    return phrases


# ════════════════════════════════════════════════════
# Tests: Basic Navigation
# ════════════════════════════════════════════════════

class TestBasicNavigation:

    def test_full_forward_traversal(self):
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, BASIC_HTML)
        expected = [
            "document",
            "navigation, Main",
            "link, Home",
            "link, About",
            "end of navigation, Main",
            "main",
            "heading, Title, level 1",
            "heading, Subtitle, level 2",
            "button, Click",
            "end of main",
            "contentinfo",
            "button, Footer Action",
            "end of contentinfo",
            "end of document",
        ]
        assert phrases == expected

    def test_wrapping_forward(self):
        sr = VirtualScreenReader()
        sr.start(BASIC_HTML)
        for _ in range(13):
            sr.next()
        assert sr.current() == "end of document"
        assert sr.next() == "document"

    def test_backward_navigation(self):
        sr = VirtualScreenReader()
        sr.start(BASIC_HTML)
        assert sr.previous() == "end of document"
        assert sr.previous() == "end of contentinfo"
        assert sr.previous() == "button, Footer Action"


# ════════════════════════════════════════════════════
# Tests: aria-owns Tree Restructuring
# ════════════════════════════════════════════════════

class TestAriaOwns:

    def test_reparenting(self):
        """Elements referenced by aria-owns appear under the owning element,
        removed from their original DOM position."""
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, OWNS_HTML)
        expected = [
            "document",
            "tablist, Settings",
            "tab, General",
            "tab, Advanced",
            "tab, Expert",
            "end of tablist, Settings",
            "main",
            "heading, Content, level 1",
            "end of main",
            "end of document",
        ]
        assert phrases == expected

    def test_circular_prevention(self):
        """Circular aria-owns references must not cause infinite loops.
        First owner in DOM order wins; back-reference is ignored."""
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, OWNS_CIRCULAR_HTML)
        expected = [
            "document",
            "group, Group A",
            "button, In A",
            "group, Group B",
            "button, In B",
            "end of group, Group B",
            "end of group, Group A",
            "end of document",
        ]
        assert phrases == expected

    def test_owned_hidden_excluded(self):
        """If an aria-owns target is hidden, it does not appear in the tree."""
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, OWNS_HIDDEN_HTML)
        expected = [
            "document",
            "tablist, Tabs",
            "tab, Visible Tab",
            "end of tablist, Tabs",
            "end of document",
        ]
        assert phrases == expected


# ════════════════════════════════════════════════════
# Tests: Presentational Children Inheritance
# ════════════════════════════════════════════════════

class TestPresentationalChildren:

    def test_table_presentation(self):
        """table with role=presentation: tr and td inherit presentation,
        text content is promoted directly."""
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, PRES_TABLE_HTML)
        expected = [
            "document",
            "main",
            "Name",
            "Alice",
            "Role",
            "Engineer",
            "end of main",
            "end of document",
        ]
        assert phrases == expected

    def test_list_none(self):
        """ul with role=none: li elements inherit presentational role,
        text content promoted."""
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, PRES_LIST_HTML)
        expected = [
            "document",
            "main",
            "Alpha",
            "Beta",
            "Gamma",
            "end of main",
            "end of document",
        ]
        assert phrases == expected

    def test_explicit_role_overrides(self):
        """A required owned element with an explicit role attribute does
        NOT inherit presentation — the explicit role takes precedence."""
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, PRES_EXPLICIT_HTML)
        expected = [
            "document",
            "main",
            "Text",
            "button, Action",
            "end of main",
            "end of document",
        ]
        assert phrases == expected


# ════════════════════════════════════════════════════
# Tests: Accessible Value
# ════════════════════════════════════════════════════

class TestAccessibleValue:

    def test_valuenow(self):
        """Widget roles include aria-valuenow in spoken phrase."""
        sr = VirtualScreenReader()
        sr.start(VALUE_HTML)
        sr.next()  # main
        assert sr.next() == "slider, Volume, 50"

    def test_valuetext_overrides(self):
        """aria-valuetext takes priority over aria-valuenow."""
        sr = VirtualScreenReader()
        sr.start(VALUE_HTML)
        sr.next()  # main
        sr.next()  # slider, Volume, 50
        assert sr.next() == "slider, Speed, Medium"

    def test_full_value_traversal(self):
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, VALUE_HTML)
        expected = [
            "document",
            "main",
            "slider, Volume, 50",
            "slider, Speed, Medium",
            "progressbar, Upload, 75",
            "end of main",
            "end of document",
        ]
        assert phrases == expected


# ════════════════════════════════════════════════════
# Tests: Embedded Control Values in ACCNAME
# ════════════════════════════════════════════════════

class TestEmbeddedControlInName:

    def test_labelledby_embedded_control(self):
        """When computing name via aria-labelledby, embedded form controls
        contribute their accessible value (ACCNAME 1.2 step 2B)."""
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, EMBEDDED_CTRL_HTML)
        expected = [
            "document",
            "main",
            "Speed",
            "slider, 5",
            "group, Speed 5",
            "button, Apply",
            "end of group, Speed 5",
            "end of main",
            "end of document",
        ]
        assert phrases == expected


# ════════════════════════════════════════════════════
# Tests: aria-flowto Navigation
# ════════════════════════════════════════════════════

class TestAriaFlowto:

    def test_flowto_navigation(self):
        """move_to_flowto follows aria-flowto to the referenced element."""
        sr = VirtualScreenReader()
        sr.start(FLOWTO_HTML)
        sr.move_to_next_landmark()  # region, Intro

        assert sr.move_to_flowto() == "region, Summary"
        assert sr.move_to_flowto() == "region, Details"

    def test_flowto_no_target(self):
        """move_to_flowto returns '' when element has no aria-flowto."""
        sr = VirtualScreenReader()
        sr.start(FLOWTO_HTML)
        sr.move_to_next_landmark()  # Intro
        sr.move_to_flowto()  # Summary
        sr.move_to_flowto()  # Details

        result = sr.move_to_flowto()
        assert result == ""
        assert sr.current() == "region, Details"


# ════════════════════════════════════════════════════
# Tests: Hidden, Modal, Inert
# ════════════════════════════════════════════════════

class TestHiddenElements:

    def test_hidden_excluded(self):
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, HIDDEN_HTML)
        expected = [
            "document",
            "main",
            "heading, Visible, level 1",
            "button, Active",
            "end of main",
            "end of document",
        ]
        assert phrases == expected


class TestModalDialog:

    def test_modal_restricts(self):
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, MODAL_HTML)
        expected = [
            "dialog, Confirm",
            "heading, Sure?, level 2",
            "button, Yes",
            "button, No",
            "end of dialog, Confirm",
        ]
        assert phrases == expected

    def test_modal_wraps(self):
        sr = VirtualScreenReader()
        sr.start(MODAL_HTML)
        sr.next()  # heading
        sr.next()  # Yes
        sr.next()  # No
        sr.next()  # end of dialog
        assert sr.next() == "dialog, Confirm"


class TestInertElements:

    def test_inert_excluded(self):
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, INERT_HTML)
        expected = [
            "document",
            "main",
            "heading, Active Content, level 2",
            "button, Active Button",
            "end of main",
            "end of document",
        ]
        assert phrases == expected


# ════════════════════════════════════════════════════
# Tests: Role & Landmark Navigation
# ════════════════════════════════════════════════════

class TestRoleNavigation:

    def test_move_to_next_heading(self):
        sr = VirtualScreenReader()
        sr.start(BASIC_HTML)
        assert sr.move_to_next("heading") == "heading, Title, level 1"
        assert sr.move_to_next("heading") == "heading, Subtitle, level 2"
        assert sr.move_to_next("heading") == "heading, Title, level 1"

    def test_move_to_nonexistent_role(self):
        sr = VirtualScreenReader()
        sr.start(BASIC_HTML)
        assert sr.move_to_next("alertdialog") == ""
        assert sr.current() == "document"


class TestLandmarkNavigation:

    def test_landmark_cycling(self):
        sr = VirtualScreenReader()
        sr.start(BASIC_HTML)
        assert sr.move_to_next_landmark() == "navigation, Main"
        assert sr.move_to_next_landmark() == "main"
        assert sr.move_to_next_landmark() == "contentinfo"
        assert sr.move_to_next_landmark() == "navigation, Main"


# ════════════════════════════════════════════════════
# Tests: Accessible Naming
# ════════════════════════════════════════════════════

class TestAccessibleNaming:

    def test_labelledby_name(self):
        sr = VirtualScreenReader()
        sr.start(NAMING_HTML)
        sr.next()  # main
        sr.next()  # heading, Dashboard
        assert sr.next() == "navigation, Dashboard"

    def test_label_overrides_content(self):
        sr = VirtualScreenReader()
        sr.start(NAMING_HTML)
        sr.next()  # main
        sr.next()  # heading
        sr.next()  # navigation
        assert sr.next() == "link, Go home"

    def test_describedby(self):
        sr = VirtualScreenReader()
        phrases = collect_all_phrases(sr, NAMING_HTML)
        assert "button, Save, Saves changes" in phrases


# ════════════════════════════════════════════════════
# Tests: Spoken Phrase Log
# ════════════════════════════════════════════════════

class TestSpokenPhraseLog:

    def test_log_tracks_navigation(self):
        sr = VirtualScreenReader()
        sr.start(BASIC_HTML)
        sr.next()
        sr.next()
        assert sr.spoken_phrase_log() == [
            "document",
            "navigation, Main",
            "link, Home",
        ]

    def test_log_includes_role_navigation(self):
        sr = VirtualScreenReader()
        sr.start(BASIC_HTML)
        sr.move_to_next("heading")
        assert sr.spoken_phrase_log() == [
            "document",
            "heading, Title, level 1",
        ]
