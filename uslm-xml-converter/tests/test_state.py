"""
Tests for USLM-to-Git backfill pipeline.

"""
import json
import os
import re
import subprocess
import yaml
import pytest

REPO = "/app/output/repo"
CHAPTER_PATH = (
    "uscode/title-99-data-governance-and-digital-infrastructure"
    "/chapter-001-general-provisions.md"
)


def git(*args):
    """Run a git command in the repo and return stdout."""
    result = subprocess.run(
        ["git", "-C", REPO, *args],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


def get_commits():
    """Get list of commit SHAs in chronological order (oldest first)."""
    output = git("rev-list", "refs/heads/main", "--reverse")
    return [s for s in output.split("\n") if s]


def get_chapter_content(commit_idx):
    """Get chapter Markdown content at a specific commit index (0-based)."""
    commits = get_commits()
    return git("show", f"{commits[commit_idx]}:{CHAPTER_PATH}")


def parse_frontmatter(content):
    """Parse YAML frontmatter from markdown content."""
    match = re.match(r'^---\n(.*?)\n---\n(.*)', content, re.DOTALL)
    assert match, "No valid YAML frontmatter found"
    fm = yaml.safe_load(match.group(1))
    body = match.group(2)
    return fm, body


# ---------------------------------------------------------------------------
# Git Structure
# ---------------------------------------------------------------------------

class TestGitStructure:
    def test_repo_exists(self):
        assert os.path.isdir(os.path.join(REPO, ".git")), "Git repo not found"

    def test_commit_count(self):
        commits = get_commits()
        assert len(commits) == 3, f"Expected 3 commits, got {len(commits)}"

    def test_commit_chronological_order(self):
        commits = get_commits()
        dates = []
        for sha in commits:
            date_str = git("log", "--format=%aI", "-1", sha)
            dates.append(date_str)
        assert dates[0] < dates[1] < dates[2], (
            f"Commits not in chronological order: {dates}"
        )

    def test_commit_author_dates(self):
        commits = get_commits()
        expected = ["2026-01-15", "2026-07-01", "2027-03-01"]
        for sha, exp in zip(commits, expected):
            date = git("log", "--format=%aI", "-1", sha)
            assert date.startswith(exp), (
                f"Commit {sha[:8]} author date {date} != {exp}*"
            )

    def test_commit_committer_dates(self):
        commits = get_commits()
        expected = ["2026-01-15", "2026-07-01", "2027-03-01"]
        for sha, exp in zip(commits, expected):
            date = git("log", "--format=%cI", "-1", sha)
            assert date.startswith(exp), (
                f"Commit {sha[:8]} committer date {date} != {exp}*"
            )

    def test_commit_subjects(self):
        commits = get_commits()
        expected = [
            "Update US Code through Public Law 119-42",
            "Update US Code through Public Law 119-73",
            "Update US Code through Public Law 120-15",
        ]
        for sha, exp in zip(commits, expected):
            subject = git("log", "--format=%s", "-1", sha)
            assert subject == exp, (
                f"Commit {sha[:8]}: {subject!r} != {exp!r}"
            )

    def test_commit_bodies(self):
        commits = get_commits()
        expected = [
            "Release point: 119-42\nYear: 2026",
            "Release point: 119-73\nYear: 2026",
            "Release point: 120-15\nYear: 2027",
        ]
        for sha, exp in zip(commits, expected):
            body = git("log", "--format=%b", "-1", sha).strip()
            assert body == exp, (
                f"Commit {sha[:8]} body:\n{body!r}\n!=\n{exp!r}"
            )

    def test_author_identity(self):
        commits = get_commits()
        for sha in commits:
            name = git("log", "--format=%an", "-1", sha)
            email = git("log", "--format=%ae", "-1", sha)
            assert name == "US Congress", f"Author name: {name!r}"
            assert email == "uscode@house.gov", f"Author email: {email!r}"

    def test_committer_identity(self):
        commits = get_commits()
        for sha in commits:
            name = git("log", "--format=%cn", "-1", sha)
            email = git("log", "--format=%ce", "-1", sha)
            assert name == "usc-backfill", f"Committer name: {name!r}"
            assert email == "sync@us-code-tools.local", (
                f"Committer email: {email!r}"
            )


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class TestTags:
    def test_tags_exist(self):
        tags = git("tag", "-l").split("\n")
        for expected in ["annual/2026", "annual/2027", "congress/119"]:
            assert expected in tags, (
                f"Tag {expected} not found. Tags: {tags}"
            )

    def test_tag_annual_2026_target(self):
        commits = get_commits()
        tag_commit = git("rev-parse", "annual/2026^{commit}")
        assert tag_commit == commits[1], (
            f"annual/2026 -> {tag_commit[:8]}, expected commit 2 ({commits[1][:8]})"
        )

    def test_tag_congress_119_target(self):
        commits = get_commits()
        tag_commit = git("rev-parse", "congress/119^{commit}")
        assert tag_commit == commits[1], (
            f"congress/119 -> {tag_commit[:8]}, expected commit 2 ({commits[1][:8]})"
        )

    def test_tag_annual_2027_target(self):
        commits = get_commits()
        tag_commit = git("rev-parse", "annual/2027^{commit}")
        assert tag_commit == commits[2], (
            f"annual/2027 -> {tag_commit[:8]}, expected commit 3 ({commits[2][:8]})"
        )

    def test_tags_are_annotated(self):
        for tag in ["annual/2026", "annual/2027", "congress/119"]:
            obj_type = git("cat-file", "-t", tag)
            assert obj_type == "tag", (
                f"{tag} is {obj_type}, expected annotated tag"
            )


# ---------------------------------------------------------------------------
# Commit Content
# ---------------------------------------------------------------------------

class TestCommitContent:
    def test_commit1_has_chapter_file(self):
        commits = get_commits()
        files = git("ls-tree", "-r", "--name-only", commits[0]).split("\n")
        assert CHAPTER_PATH in files

    def test_commit2_has_chapter_file(self):
        commits = get_commits()
        files = git("ls-tree", "-r", "--name-only", commits[1]).split("\n")
        assert CHAPTER_PATH in files

    def test_commit3_has_chapter_file(self):
        commits = get_commits()
        files = git("ls-tree", "-r", "--name-only", commits[2]).split("\n")
        assert CHAPTER_PATH in files

    def test_commit1_section_count(self):
        content = get_chapter_content(0)
        fm, _ = parse_frontmatter(content)
        assert fm["section_count"] == 3

    def test_commit2_section_count(self):
        content = get_chapter_content(1)
        fm, _ = parse_frontmatter(content)
        assert fm["section_count"] == 4

    def test_commit3_section_count(self):
        content = get_chapter_content(2)
        fm, _ = parse_frontmatter(content)
        assert fm["section_count"] == 4

    def test_commit1_frontmatter(self):
        content = get_chapter_content(0)
        fm, _ = parse_frontmatter(content)
        assert fm["title"] == 99
        assert str(fm["chapter"]) == "1"
        assert fm["heading"] == "GENERAL PROVISIONS"
        assert "USC-prelim-title99" in fm["source"]

    def test_commit2_has_section_104(self):
        content = get_chapter_content(1)
        assert '<a id="section-104"></a>' in content
        assert "\u00a7 104." in content

    def test_commit1_no_section_104(self):
        content = get_chapter_content(0)
        assert "section-104" not in content


# ---------------------------------------------------------------------------
# Markdown Quality
# ---------------------------------------------------------------------------

class TestMarkdownQuality:
    def test_section_anchors_commit1(self):
        content = get_chapter_content(0)
        for n in ["101", "102", "103"]:
            assert f'<a id="section-{n}"></a>' in content

    def test_section_anchors_commit2(self):
        content = get_chapter_content(1)
        for n in ["101", "102", "103", "104"]:
            assert f'<a id="section-{n}"></a>' in content

    def test_cross_ref_title5(self):
        content = get_chapter_content(0)
        expected = (
            "[section 551 of title 5]"
            "(https://uscode.house.gov/view.xhtml?"
            "req=granuleid:USC-prelim-title5-section551"
            "&num=0&edition=prelim)"
        )
        assert expected in content

    def test_cross_ref_title15(self):
        content = get_chapter_content(0)
        expected = (
            "[section 45 of title 15]"
            "(https://uscode.house.gov/view.xhtml?"
            "req=granuleid:USC-prelim-title15-section45"
            "&num=0&edition=prelim)"
        )
        assert expected in content

    def test_cross_ref_self_title(self):
        content = get_chapter_content(0)
        expected = (
            "[section 102 of this title]"
            "(https://uscode.house.gov/view.xhtml?"
            "req=granuleid:USC-prelim-title99-section102"
            "&num=0&edition=prelim)"
        )
        assert expected in content

    def test_bold_subsection_labels(self):
        content = get_chapter_content(0)
        assert "**(a)**" in content
        assert "**(b)**" in content

    def test_subparagraph_indentation(self):
        content = get_chapter_content(0)
        assert "\n  (A) identifies" in content
        assert "\n  (B) is collected" in content

    def test_clause_indentation(self):
        content = get_chapter_content(0)
        assert "\n    (i) the internet" in content
        assert "\n    (ii) a device" in content

    def test_subclause_indentation(self):
        content = get_chapter_content(0)
        assert "\n      (I) biometric" in content
        assert "\n      (II) geolocation" in content
        assert "\n      (III) health" in content

    def test_continuation_no_blank_line(self):
        content = get_chapter_content(0)
        assert "(III) health data.\n  Such term" in content

    def test_statutory_notes(self):
        content = get_chapter_content(0)
        assert "### Statutory Notes" in content
        assert "#### References in Text" in content
        assert "#### Effective Date" in content
        assert "#### Regulations" in content

    def test_editorial_notes(self):
        content = get_chapter_content(0)
        assert "### Notes" in content
        assert "substituted" in content

    def test_commit2_large_data_holder(self):
        content = get_chapter_content(1)
        assert "large data holder" in content
        assert "5,000,000" in content

    def test_commit2_data_portability(self):
        content = get_chapter_content(1)
        assert "**(d)**" in content
        assert "portable, machine-readable format" in content

    def test_commit3_penalty_75000(self):
        content = get_chapter_content(2)
        assert "$75,000" in content

    def test_commit3_penalty_200000(self):
        content = get_chapter_content(2)
        assert "$200,000" in content

    def test_commit3_editorial_notes_updated(self):
        content = get_chapter_content(2)
        assert "120\u201315" in content or "120-15" in content


# ---------------------------------------------------------------------------
# Diffs
# ---------------------------------------------------------------------------

class TestDiffs:
    def test_diff_1_to_2_adds_section_104(self):
        commits = get_commits()
        diff = git("diff", commits[0], commits[1])
        assert "104" in diff
        assert "Annual reporting" in diff or "annual reporting" in diff.lower()

    def test_diff_1_to_2_adds_large_data_holder(self):
        commits = get_commits()
        diff = git("diff", commits[0], commits[1])
        assert "large data holder" in diff

    def test_diff_2_to_3_changes_penalty(self):
        commits = get_commits()
        diff = git("diff", commits[1], commits[2])
        assert "$75,000" in diff
        assert "$200,000" in diff

    def test_diff_1_to_2_adds_portability(self):
        commits = get_commits()
        diff = git("diff", commits[0], commits[1])
        assert "portable" in diff.lower()


# ---------------------------------------------------------------------------
# Cross-Reference Integrity Report
# ---------------------------------------------------------------------------

class TestRefsReport:
    def test_report_exists(self):
        path = os.path.join(REPO, "refs-report.json")
        assert os.path.isfile(path), "refs-report.json not found in repo root"

    def test_report_valid_json(self):
        path = os.path.join(REPO, "refs-report.json")
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_report_has_references_array(self):
        with open(os.path.join(REPO, "refs-report.json")) as f:
            data = json.load(f)
        assert "references" in data
        assert isinstance(data["references"], list)

    def test_report_has_summary(self):
        with open(os.path.join(REPO, "refs-report.json")) as f:
            data = json.load(f)
        assert "summary" in data
        summary = data["summary"]
        assert "total" in summary
        assert "internal" in summary
        assert "external" in summary

    def test_report_total_count(self):
        with open(os.path.join(REPO, "refs-report.json")) as f:
            data = json.load(f)
        assert data["summary"]["total"] == 5, (
            f"Expected 5 total refs, got {data['summary']['total']}"
        )

    def test_report_internal_count(self):
        with open(os.path.join(REPO, "refs-report.json")) as f:
            data = json.load(f)
        assert data["summary"]["internal"] == 2, (
            f"Expected 2 internal refs, got {data['summary']['internal']}"
        )

    def test_report_external_count(self):
        with open(os.path.join(REPO, "refs-report.json")) as f:
            data = json.load(f)
        assert data["summary"]["external"] == 3, (
            f"Expected 3 external refs, got {data['summary']['external']}"
        )

    def test_report_reference_structure(self):
        with open(os.path.join(REPO, "refs-report.json")) as f:
            data = json.load(f)
        for ref in data["references"]:
            assert "target_title" in ref, "Missing target_title"
            assert "target_section" in ref, "Missing target_section"
            assert "internal" in ref, "Missing internal flag"
            assert isinstance(ref["target_title"], int)
            assert isinstance(ref["internal"], bool)

    def test_report_contains_title5_ref(self):
        with open(os.path.join(REPO, "refs-report.json")) as f:
            data = json.load(f)
        t5 = [r for r in data["references"] if r["target_title"] == 5]
        assert len(t5) >= 1, "No reference to title 5 found"

    def test_report_contains_title15_ref(self):
        with open(os.path.join(REPO, "refs-report.json")) as f:
            data = json.load(f)
        t15 = [r for r in data["references"] if r["target_title"] == 15]
        assert len(t15) >= 1, "No reference to title 15 found"

    def test_report_internal_refs_are_title99(self):
        with open(os.path.join(REPO, "refs-report.json")) as f:
            data = json.load(f)
        t99 = [r for r in data["references"] if r["target_title"] == 99]
        assert len(t99) == 2, f"Expected 2 refs to title 99, got {len(t99)}"
        assert all(r["internal"] for r in t99), "Title 99 refs should be internal"

    def test_report_external_refs_not_internal(self):
        with open(os.path.join(REPO, "refs-report.json")) as f:
            data = json.load(f)
        external = [r for r in data["references"] if r["target_title"] != 99]
        assert all(not r["internal"] for r in external), (
            "Non-title-99 refs should be external"
        )


# ---------------------------------------------------------------------------
# Changelog
# ---------------------------------------------------------------------------

class TestChangelog:
    def _load(self):
        path = os.path.join(REPO, "changelog.json")
        with open(path) as f:
            return json.load(f)

    def test_changelog_exists(self):
        assert os.path.isfile(os.path.join(REPO, "changelog.json")), (
            "changelog.json not found in repo root"
        )

    def test_changelog_valid_json(self):
        data = self._load()
        assert isinstance(data, dict)

    def test_changelog_has_diffs_array(self):
        data = self._load()
        assert "diffs" in data
        assert isinstance(data["diffs"], list)
        assert len(data["diffs"]) == 2, (
            f"Expected 2 diffs (3 vintages - 1), got {len(data['diffs'])}"
        )

    def test_first_diff_vintages(self):
        data = self._load()
        d = data["diffs"][0]
        assert d["from_vintage"] == "119-42", (
            f"First diff from_vintage: {d['from_vintage']!r}, expected '119-42'"
        )
        assert d["to_vintage"] == "119-73", (
            f"First diff to_vintage: {d['to_vintage']!r}, expected '119-73'"
        )

    def test_second_diff_vintages(self):
        data = self._load()
        d = data["diffs"][1]
        assert d["from_vintage"] == "119-73", (
            f"Second diff from_vintage: {d['from_vintage']!r}, expected '119-73'"
        )
        assert d["to_vintage"] == "120-15", (
            f"Second diff to_vintage: {d['to_vintage']!r}, expected '120-15'"
        )

    def test_first_diff_section_104_added(self):
        data = self._load()
        changes = data["diffs"][0]["changes"]
        adds = [
            c for c in changes
            if c["change_type"] == "section_added" and c["section"] == "104"
        ]
        assert len(adds) >= 1, "Section 104 should be listed as added"
        assert adds[0]["heading"] == "Annual reporting", (
            f"Section 104 heading: {adds[0].get('heading')!r}"
        )

    def test_first_diff_subsection_d_added(self):
        data = self._load()
        changes = data["diffs"][0]["changes"]
        adds = [
            c for c in changes
            if c["change_type"] == "subsection_added" and c["section"] == "102"
        ]
        assert len(adds) >= 1, (
            "Subsection (d) of section 102 should be listed as added"
        )

    def test_first_diff_paragraph_added(self):
        data = self._load()
        changes = data["diffs"][0]["changes"]
        adds = [
            c for c in changes
            if c["change_type"] == "paragraph_added" and c["section"] == "101"
        ]
        assert len(adds) >= 1, (
            "Paragraph (5) of section 101(a) should be listed as added"
        )

    def test_first_diff_no_text_amendments(self):
        """No text was amended between 119-42 and 119-73 in existing provisions."""
        data = self._load()
        changes = data["diffs"][0]["changes"]
        amends = [c for c in changes if c["change_type"] == "text_amended"]
        assert len(amends) == 0, (
            f"Unexpected text amendments in first diff: {amends}"
        )

    def test_second_diff_text_amended_count(self):
        data = self._load()
        changes = data["diffs"][1]["changes"]
        amends = [
            c for c in changes
            if c["change_type"] == "text_amended" and c["section"] == "103"
        ]
        assert len(amends) >= 2, (
            f"Expected >= 2 text amendments in section 103, got {len(amends)}"
        )

    def test_second_diff_penalty_values(self):
        data = self._load()
        changes = data["diffs"][1]["changes"]
        amends = [c for c in changes if c["change_type"] == "text_amended"]
        all_json = json.dumps(amends)
        assert "75,000" in all_json or "75000" in all_json, (
            "Penalty change to $75,000 not found in text_amended entries"
        )
        assert "200,000" in all_json or "200000" in all_json, (
            "Penalty change to $200,000 not found in text_amended entries"
        )

    def test_second_diff_notes_amended(self):
        data = self._load()
        changes = data["diffs"][1]["changes"]
        notes = [
            c for c in changes
            if c["change_type"] == "notes_amended" and c["section"] == "103"
        ]
        assert len(notes) >= 1, (
            "Editorial notes amendment in section 103 not found"
        )
        assert notes[0]["note_type"] == "editorial", (
            f"Expected editorial note_type, got {notes[0].get('note_type')!r}"
        )

    def test_second_diff_no_section_additions(self):
        """No new sections between 119-73 and 120-15."""
        data = self._load()
        changes = data["diffs"][1]["changes"]
        adds = [c for c in changes if c["change_type"] == "section_added"]
        assert len(adds) == 0, (
            f"Unexpected section additions in second diff: {adds}"
        )

    def test_changelog_change_types_valid(self):
        valid = {
            "section_added", "subsection_added", "paragraph_added",
            "text_amended", "notes_amended",
        }
        data = self._load()
        for diff in data["diffs"]:
            for change in diff["changes"]:
                assert change["change_type"] in valid, (
                    f"Invalid change_type: {change['change_type']}"
                )

    def test_changelog_change_structure(self):
        data = self._load()
        for diff in data["diffs"]:
            assert "from_vintage" in diff
            assert "to_vintage" in diff
            assert "changes" in diff
            assert isinstance(diff["changes"], list)
            for change in diff["changes"]:
                assert "change_type" in change, "Missing change_type"
                assert "section" in change, "Missing section"


# ---------------------------------------------------------------------------
# Anti-cheat
# ---------------------------------------------------------------------------

class TestAntiCheat:
    def test_uses_fast_import(self):
        source = open("/app/backfill.py").read()
        assert "fast-import" in source or "fast_import" in source, (
            "Solution must use git fast-import"
        )

    def test_parses_xml(self):
        """Verify the solution parses XML rather than hardcoding output."""
        source = open("/app/backfill.py").read().lower()
        xml_indicators = ["xml", "elementtree", "etree", "lxml", "parse"]
        assert any(ind in source for ind in xml_indicators), (
            "Solution must parse XML input"
        )
