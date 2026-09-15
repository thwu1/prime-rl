"""
Tests for USLM XML to Markdown converter.

"""
import os
import re
import yaml
import pytest

OUTPUT_DIR = "/app/output"
TITLE_DIR = os.path.join(OUTPUT_DIR, "title-99-digital-infrastructure")


def read_section(section_num: str) -> str:
    """Read a section markdown file and return its content."""
    padded = str(section_num).zfill(5)
    path = os.path.join(TITLE_DIR, f"section-{padded}.md")
    assert os.path.isfile(path), f"Missing output file: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from markdown content."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    assert match, "Could not parse YAML frontmatter"
    return yaml.safe_load(match.group(1))


def get_body(content: str) -> str:
    """Get the body content after frontmatter."""
    match = re.match(r"^---\s*\n.*?\n---\s*\n(.*)", content, re.DOTALL)
    assert match, "Could not extract body"
    return match.group(1)


# ───────────────────────── Output structure ─────────────────────────


class TestOutputStructure:
    def test_output_directory_exists(self):
        assert os.path.isdir(TITLE_DIR), (
            f"Output directory {TITLE_DIR} does not exist"
        )

    def test_output_directory_name(self):
        dirs = [
            d for d in os.listdir(OUTPUT_DIR)
            if os.path.isdir(os.path.join(OUTPUT_DIR, d))
        ]
        assert "title-99-digital-infrastructure" in dirs

    def test_section_files_exist(self):
        for num in ["101", "102", "103", "104"]:
            padded = num.zfill(5)
            path = os.path.join(TITLE_DIR, f"section-{padded}.md")
            assert os.path.isfile(path), f"Missing: section-{padded}.md"

    def test_no_extra_section_files(self):
        """Only 4 real sections; the embedded section in the note must NOT
        produce its own output file."""
        section_files = [
            f for f in os.listdir(TITLE_DIR)
            if f.startswith("section-") and f.endswith(".md")
        ]
        assert len(section_files) == 4, (
            f"Expected 4 section files, got {len(section_files)}: {section_files}"
        )

    def test_file_naming_convention(self):
        for f in os.listdir(TITLE_DIR):
            if f.endswith(".md"):
                assert re.match(r"^section-\d{5}\.md$", f), (
                    f"File name {f} does not match section-NNNNN.md pattern"
                )


# ───────────────────────── Section 101: Definitions ─────────────────────────


class TestSection101Frontmatter:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.content = read_section("101")
        self.fm = parse_frontmatter(self.content)

    def test_title(self):
        assert self.fm["title"] == 99

    def test_section(self):
        assert str(self.fm["section"]) == "101"

    def test_heading(self):
        assert self.fm["heading"] == "Definitions"

    def test_status(self):
        assert self.fm["status"] == "in-force"

    def test_source_url(self):
        src = self.fm["source"]
        assert "title99" in src
        assert "section101" in src
        assert "uscode.house.gov" in src

    def test_chapter(self):
        assert str(self.fm["chapter"]) == "1"

    def test_enacted(self):
        assert str(self.fm["enacted"]) == "2024-03-15"

    def test_public_law(self):
        assert "118" in self.fm["public_law"]
        assert "200" in self.fm["public_law"]

    def test_last_amended(self):
        assert str(self.fm["last_amended"]) == "2025-01-10"

    def test_last_amended_by(self):
        assert "119" in self.fm["last_amended_by"]

    def test_source_credit(self):
        sc = self.fm["source_credit"]
        assert "Pub. L." in sc
        assert "118" in sc
        assert "1001" in sc
        assert "119" in sc


class TestSection101Body:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.body = get_body(read_section("101"))

    def test_section_heading(self):
        assert "# § 101. Definitions" in self.body

    def test_subsection_a_bold_label(self):
        assert "**(a)**" in self.body

    def test_subsection_a_chapeau(self):
        assert "As used in this chapter" in self.body

    def test_paragraph_1_label(self):
        lines = self.body.split("\n")
        para1_lines = [l for l in lines if l.strip().startswith("(1)")]
        assert len(para1_lines) >= 1, "Missing paragraph (1)"
        # Paragraph label should NOT be bold
        for line in para1_lines:
            assert "**" not in line.split("(1)")[0], (
                "Paragraph (1) label should not be bold"
            )

    def test_subparagraph_indent(self):
        lines = self.body.split("\n")
        subpara_a = [l for l in lines if "(A)" in l and "utilizes" in l]
        assert len(subpara_a) >= 1, "Missing subparagraph (A)"
        line = subpara_a[0]
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        assert indent == 2, f"Subparagraph (A) should be indented 2, got {indent}"

    def test_clause_indent(self):
        lines = self.body.split("\n")
        clause_i = [l for l in lines if "(i)" in l and "fiber optic" in l]
        assert len(clause_i) >= 1, "Missing clause (i)"
        line = clause_i[0]
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        assert indent == 4, f"Clause (i) should be indented 4, got {indent}"

    def test_clause_ii(self):
        assert "wireless communication towers" in self.body

    def test_clause_iii(self):
        assert "satellite ground stations" in self.body

    def test_clause_iv(self):
        assert "data center facilities" in self.body

    def test_paragraph_2(self):
        assert "covered entity" in self.body
        assert "100,000 users" in self.body

    def test_paragraph_3_chapeau(self):
        assert "critical vulnerability" in self.body
        assert "security flaw" in self.body

    def test_subsection_b_bold_with_heading(self):
        assert "**(b)" in self.body
        assert "Rules of construction" in self.body

    def test_blank_lines_between_labeled_elements(self):
        """Labeled elements should be separated by blank lines."""
        lines = self.body.split("\n")
        prev_was_labeled = False
        prev_was_blank = False
        for line in lines:
            is_labeled = bool(re.match(r"^\s*(\*\*)?\([a-zA-Z0-9]+\)", line))
            if is_labeled and prev_was_labeled and not prev_was_blank:
                pytest.fail(
                    f"Missing blank line between labeled elements near: {line}"
                )
            prev_was_labeled = is_labeled or (prev_was_labeled and line.strip() == "")
            prev_was_blank = line.strip() == ""


class TestSection101CrossRefs:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.body = get_body(read_section("101"))

    def test_title_42_link(self):
        """Cross-reference to title 42 section 5195c."""
        assert "title-42" in self.body
        assert "section-05195c" in self.body
        # Should be a markdown link
        match = re.search(
            r"\[.*?section 5195c.*?\]\(.*?title-42.*?section-05195c.*?\.md\)",
            self.body,
            re.IGNORECASE,
        )
        assert match, "Missing cross-reference link to title 42 section 5195c"

    def test_title_42_slug(self):
        """Title 42 slug should include 'public-health'."""
        match = re.search(r"title-42-[a-z-]+/", self.body)
        assert match, "Missing title-42 directory reference"
        assert "public-health" in match.group(0).lower()

    def test_section_103_link(self):
        """Cross-reference to section 103 within the same title."""
        match = re.search(
            r"\[.*?section 103.*?\]\(.*?section-00103.*?\.md\)",
            self.body,
            re.IGNORECASE,
        )
        assert match, "Missing cross-reference link to section 103"

    def test_section_103_same_title(self):
        """Section 103 link should reference title-99-digital-infrastructure."""
        match = re.search(r"title-99-digital-infrastructure/section-00103", self.body)
        assert match, "Section 103 link should use title-99-digital-infrastructure"

    def test_title_6_link(self):
        """Cross-reference to title 6 section 652."""
        match = re.search(
            r"\[.*?section 652.*?\]\(.*?title-06.*?section-00652.*?\.md\)",
            self.body,
            re.IGNORECASE,
        )
        assert match, "Missing cross-reference link to title 6 section 652"

    def test_title_6_slug(self):
        """Title 6 slug should include 'domestic-security'."""
        match = re.search(r"title-06-[a-z-]+/", self.body)
        assert match, "Missing title-06 directory reference"
        assert "domestic-security" in match.group(0).lower()


# ───────────────────────── Section 102: Reporting ─────────────────────────


class TestSection102Frontmatter:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.content = read_section("102")
        self.fm = parse_frontmatter(self.content)

    def test_title(self):
        assert self.fm["title"] == 99

    def test_section(self):
        assert str(self.fm["section"]) == "102"

    def test_heading(self):
        assert self.fm["heading"] == "Reporting requirements"

    def test_no_last_amended(self):
        assert self.fm.get("last_amended") is None

    def test_no_last_amended_by(self):
        assert self.fm.get("last_amended_by") is None

    def test_source_credit(self):
        sc = self.fm["source_credit"]
        assert "1003" in sc


class TestSection102Body:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.body = get_body(read_section("102"))

    def test_section_heading(self):
        assert "# § 102. Reporting requirements" in self.body

    def test_subsection_a_heading(self):
        """Subsection (a) should have heading 'In general'."""
        assert "**(a)" in self.body
        assert "In general" in self.body

    def test_subsection_b_heading_with_chapeau(self):
        """Subsection (b) with heading and chapeau text."""
        assert "**(b)" in self.body
        assert "Contents" in self.body
        assert "Each report submitted under subsection (a) shall include" in self.body

    def test_paragraph_structure(self):
        assert "(1)" in self.body
        assert "description of the digital infrastructure" in self.body
        assert "(2)" in self.body
        assert "assessment of vulnerabilities" in self.body
        assert "(3)" in self.body
        assert "certification of compliance" in self.body

    def test_nested_subparagraphs(self):
        """Paragraph (2) should have subparagraphs (A) and (B)."""
        lines = self.body.split("\n")
        sub_a = [l for l in lines if "(A)" in l and "critical vulnerability" in l]
        assert len(sub_a) >= 1, "Missing subparagraph (A) under paragraph (2)"

        sub_b = [l for l in lines if "(B)" in l and "remediation" in l]
        assert len(sub_b) >= 1, "Missing subparagraph (B) under paragraph (2)"

    def test_subsection_c_heading(self):
        assert "**(c)" in self.body
        assert "Deadline" in self.body
        assert "90 days" in self.body


class TestSection102CrossRefs:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.body = get_body(read_section("102"))

    def test_section_101_link_in_subsection_a(self):
        """Reference to section 101 should be a markdown link."""
        match = re.search(
            r"\[.*?section 101.*?\]\(.*?section-00101.*?\.md\)",
            self.body,
            re.IGNORECASE,
        )
        assert match, "Missing link to section 101 in subsection (a)"

    def test_section_101_link_in_subparagraph(self):
        """Reference to section 101 in subparagraph (A)."""
        assert "section 101" in self.body

    def test_title_15_link(self):
        """Cross-reference to title 15 section 7431."""
        match = re.search(
            r"\[.*?section 7431.*?\]\(.*?title-15.*?section-07431.*?\.md\)",
            self.body,
            re.IGNORECASE,
        )
        assert match, "Missing link to title 15 section 7431"

    def test_title_15_slug(self):
        """Title 15 slug should include 'commerce'."""
        match = re.search(r"title-15-[a-z-]+/", self.body)
        assert match, "Missing title-15 directory reference"
        assert "commerce" in match.group(0).lower()


# ───────────────────────── Section 103: Penalties ─────────────────────────


class TestSection103Frontmatter:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.content = read_section("103")
        self.fm = parse_frontmatter(self.content)

    def test_title(self):
        assert self.fm["title"] == 99

    def test_section(self):
        assert str(self.fm["section"]) == "103"

    def test_heading(self):
        assert self.fm["heading"] == "Penalties"


class TestSection103Body:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.body = get_body(read_section("103"))

    def test_section_heading(self):
        assert "# § 103. Penalties" in self.body

    def test_subsection_a_civil_penalties(self):
        assert "**(a)" in self.body
        assert "Civil penalties" in self.body
        assert "$500,000" in self.body

    def test_subsection_b_criminal_penalties(self):
        assert "**(b)" in self.body
        assert "Criminal penalties" in self.body
        assert "5 years" in self.body

    def test_cross_ref_section_102(self):
        match = re.search(
            r"\[.*?section 102.*?\]\(.*?section-00102.*?\.md\)",
            self.body,
            re.IGNORECASE,
        )
        assert match, "Missing link to section 102"

    def test_cross_ref_title_18(self):
        match = re.search(
            r"\[.*?section 3571.*?\]\(.*?title-18.*?section-03571.*?\.md\)",
            self.body,
            re.IGNORECASE,
        )
        assert match, "Missing link to title 18 section 3571"


class TestSection103StatutoryNotes:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.body = get_body(read_section("103"))

    def test_statutory_notes_heading(self):
        assert "## Statutory Notes" in self.body

    def test_effective_date_heading(self):
        assert "### Effective Date" in self.body

    def test_effective_date_content(self):
        assert "180 days" in self.body

    def test_penalty_schedule_heading(self):
        assert "### Penalty Schedule" in self.body

    def test_penalty_schedule_text(self):
        assert "penalty schedule" in self.body.lower()


class TestSection103Table:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.body = get_body(read_section("103"))

    def test_table_header_row(self):
        """Table should have proper markdown header."""
        lines = self.body.split("\n")
        header_lines = [
            l for l in lines
            if "Violation Category" in l and "|" in l
        ]
        assert len(header_lines) >= 1, "Missing table header row"

    def test_table_separator(self):
        """Table should have separator row with ---."""
        lines = self.body.split("\n")
        sep_lines = [l for l in lines if re.match(r"^\s*\|[\s\-|]+\|\s*$", l)]
        assert len(sep_lines) >= 1, "Missing table separator row"

    def test_table_data_late_filing(self):
        lines = self.body.split("\n")
        late_lines = [l for l in lines if "Late filing" in l and "|" in l]
        assert len(late_lines) >= 1, "Missing 'Late filing' row"
        assert "$50,000" in late_lines[0]
        assert "$150,000" in late_lines[0]

    def test_table_data_material_omission(self):
        lines = self.body.split("\n")
        omission_lines = [
            l for l in lines if "Material omission" in l and "|" in l
        ]
        assert len(omission_lines) >= 1, "Missing 'Material omission' row"
        assert "$100,000" in omission_lines[0]
        assert "$300,000" in omission_lines[0]

    def test_table_data_willful_concealment(self):
        lines = self.body.split("\n")
        concealment_lines = [
            l for l in lines if "Willful concealment" in l and "|" in l
        ]
        assert len(concealment_lines) >= 1, "Missing 'Willful concealment' row"
        assert "$250,000" in concealment_lines[0]
        assert "$500,000" in concealment_lines[0]

    def test_table_column_count(self):
        """All table rows should have 3 data columns."""
        lines = self.body.split("\n")
        table_lines = [
            l for l in lines
            if "|" in l and (
                "Violation" in l or "Late" in l or "Material" in l
                or "Willful" in l or "---" in l or "First" in l
                or "Subsequent" in l
            )
        ]
        for line in table_lines:
            # Count pipe-delimited cells
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            assert len(cells) == 3, (
                f"Expected 3 columns, got {len(cells)} in: {line}"
            )


class TestSection103EditorialNotes:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.body = get_body(read_section("103"))

    def test_notes_heading(self):
        """Editorial notes should be under '## Notes'."""
        assert "## Notes" in self.body

    def test_editorial_note_content(self):
        assert "original enactment" in self.body
        assert "chapter 1 of title 99" in self.body

    def test_notes_section_order(self):
        """Statutory Notes should come before editorial Notes."""
        statutory_pos = self.body.index("## Statutory Notes")
        notes_pos = self.body.index("## Notes")
        assert statutory_pos < notes_pos, (
            "Statutory Notes should appear before editorial Notes"
        )


# ───────────────────── Section 104: Repealed section ─────────────────────


class TestSection104:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.content = read_section("104")
        self.fm = parse_frontmatter(self.content)
        self.body = get_body(self.content)

    def test_status_repealed(self):
        assert self.fm["status"] == "repealed"

    def test_heading(self):
        assert self.fm["heading"] == "Authorization of appropriations"

    def test_section_heading(self):
        assert "# § 104. Authorization of appropriations" in self.body

    def test_repealed_text(self):
        assert "Repealed" in self.body

    def test_source_credit(self):
        assert "repealed" in self.fm["source_credit"].lower()


class TestSection104NoteScopeBoundary:
    """The embedded <section> inside the note of section 104 must NOT
    produce its own output file — only 4 section files should exist."""

    def test_no_duplicate_section_104_file(self):
        section_files = sorted(os.listdir(TITLE_DIR))
        expected = [
            "section-00101.md",
            "section-00102.md",
            "section-00103.md",
            "section-00104.md",
        ]
        assert section_files == expected, (
            f"Unexpected files: {section_files}. "
            "The embedded section in the note of section 104 must not "
            "generate its own output file."
        )

    def test_embedded_section_in_note_text(self):
        """The embedded section inside the note should appear as text
        within the statutory note body, not as a separate file."""
        body = get_body(read_section("104"))
        # The statutory note should contain the embedded section text
        assert "authorized to be appropriated" in body
        assert "50,000,000" in body


# ───────────────────── Cross-cutting tests ─────────────────────


class TestCrossCutting:
    def test_all_files_have_frontmatter(self):
        for num in ["101", "102", "103", "104"]:
            content = read_section(num)
            assert content.startswith("---"), (
                f"Section {num} missing frontmatter delimiter"
            )
            fm = parse_frontmatter(content)
            assert "title" in fm
            assert "section" in fm

    def test_all_files_have_section_heading(self):
        for num in ["101", "102", "103", "104"]:
            body = get_body(read_section(num))
            pattern = rf"# § {num}\."
            assert re.search(pattern, body), (
                f"Section {num} missing heading '# § {num}.'"
            )

    def test_no_raw_xml_tags_in_output(self):
        for num in ["101", "102", "103", "104"]:
            body = get_body(read_section(num))
            # Should not contain raw XML tags (except markdown link syntax)
            for tag in [
                "<subsection", "<paragraph", "<subparagraph",
                "<clause", "<num", "<heading>", "<chapeau",
                "<text>", "<content>", "<ref ", "<sourceCredit",
            ]:
                assert tag not in body, (
                    f"Section {num} contains raw XML tag: {tag}"
                )

    def test_no_ref_fragments_in_links(self):
        """Links should not contain #ref= canonical fragments."""
        for num in ["101", "102", "103", "104"]:
            body = get_body(read_section(num))
            assert "#ref=" not in body, (
                f"Section {num} contains #ref= fragment in link"
            )

    def test_unicode_rendering(self):
        """Em dashes and special quotes should render correctly."""
        content_101 = read_section("101")
        # The source credit and content contain em dashes
        assert "\u2013" in content_101 or "–" in content_101 or \
               "118-200" in content_101, (
            "Section 101 should contain en dash or equivalent in public law"
        )
