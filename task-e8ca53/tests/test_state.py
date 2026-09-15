
import json
import os
import re
import subprocess

import pytest
import yaml


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_DIR = "/app/repo"
OUTPUT_DIR = "/app/output"
EN_DASH = "\u2013"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path):
    assert os.path.exists(path), f"Expected file not found: {path}"
    with open(path) as f:
        return json.load(f)


def git(args, cwd=REPO_DIR):
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=cwd, timeout=30,
    )
    return result


def git_check(args, cwd=REPO_DIR):
    result = git(args, cwd)
    assert result.returncode == 0, (
        f"git {' '.join(args)} failed: {result.stderr}"
    )
    return result.stdout.strip()


def parse_frontmatter(content):
    parts = content.split("---", 2)
    assert len(parts) >= 3, "No YAML frontmatter found"
    return yaml.safe_load(parts[1])


def get_body(content):
    parts = content.split("---", 2)
    return parts[2] if len(parts) >= 3 else content


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def run_pipeline():
    if not os.path.exists(os.path.join(REPO_DIR, ".git")):
        pipeline = "/app/pipeline.sh"
        assert os.path.exists(pipeline), (
            f"Pipeline entry point not found: {pipeline}"
        )
        result = subprocess.run(
            ["bash", pipeline],
            capture_output=True, text=True, timeout=300, cwd="/app",
        )
        assert result.returncode == 0, (
            f"pipeline.sh failed:\nstdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return True


@pytest.fixture(scope="session")
def git_commits(run_pipeline):
    hashes_output = git_check(["log", "--format=%H", "--reverse", "main"])
    hashes = hashes_output.strip().split("\n")
    commits = []
    for h in hashes:
        full_msg = git_check(["log", "-1", "--format=%B", h])
        author_date = git_check(["log", "-1", "--format=%aI", h])
        committer_date = git_check(["log", "-1", "--format=%cI", h])
        author_id = git_check(["log", "-1", "--format=%an <%ae>", h])
        lines = full_msg.strip().split("\n")
        subject = lines[0]
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        commits.append({
            "hash": h,
            "subject": subject,
            "body": body,
            "author_date": author_date,
            "committer_date": committer_date,
            "author_id": author_id,
        })
    return commits


@pytest.fixture(scope="session")
def provenance(run_pipeline):
    return load_json(os.path.join(OUTPUT_DIR, "provenance.json"))


@pytest.fixture(scope="session")
def xref_analysis(run_pipeline):
    return load_json(os.path.join(OUTPUT_DIR, "xref_analysis.json"))


@pytest.fixture(scope="session")
def changelog(run_pipeline):
    return load_json(os.path.join(OUTPUT_DIR, "changelog.json"))


# ---------------------------------------------------------------------------
# 1. Pipeline Entry Point
# ---------------------------------------------------------------------------

class TestPipelineEntryPoint:
    def test_pipeline_sh_exists(self, run_pipeline):
        assert os.path.exists("/app/pipeline.sh")

    def test_pipeline_sh_executable(self, run_pipeline):
        assert os.access("/app/pipeline.sh", os.X_OK)


# ---------------------------------------------------------------------------
# 2. Git Repository Structure
# ---------------------------------------------------------------------------

class TestGitStructure:
    def test_repo_exists(self, run_pipeline):
        assert os.path.isdir(os.path.join(REPO_DIR, ".git"))

    def test_four_commits(self, git_commits):
        assert len(git_commits) == 4, (
            f"Expected 4 commits, got {len(git_commits)}"
        )

    def test_commit_subjects(self, git_commits):
        expected = [
            "Update US Code through Public Law 116-344",
            "Update US Code through Public Law 117-81",
            "Update US Code through Public Law 117-262",
            "Update US Code through Public Law 118-82",
        ]
        actual = [c["subject"] for c in git_commits]
        assert actual == expected, f"Commit subjects: {actual}"

    def test_author_dates(self, git_commits):
        dates = [c["author_date"][:10] for c in git_commits]
        assert dates[0] == "2021-01-03"
        assert dates[1] == "2021-11-15"
        assert dates[2] == "2022-12-22"
        assert dates[3] == "2024-01-29"

    def test_committer_dates(self, git_commits):
        dates = [c["committer_date"][:10] for c in git_commits]
        assert dates[0] == "2021-01-03"
        assert dates[1] == "2021-11-15"
        assert dates[2] == "2022-12-22"
        assert dates[3] == "2024-01-29"

    def test_author_identity(self, git_commits):
        for c in git_commits:
            assert c["author_id"] == "us-code-tools <sync@us-code-tools.local>", (
                f"Unexpected author: {c['author_id']}"
            )

    def test_chronological_order(self, git_commits):
        dates = [c["author_date"] for c in git_commits]
        assert dates == sorted(dates), "Commits not chronologically ordered"


# ---------------------------------------------------------------------------
# 3. Git Commit Messages — Structured Changes
# ---------------------------------------------------------------------------

class TestGitCommitMessages:
    def test_first_commit_has_changes_block(self, git_commits):
        body = git_commits[0]["body"]
        assert "Changes:" in body, "First commit should have Changes: block"

    def test_first_commit_initial_additions(self, git_commits):
        body = git_commits[0]["body"]
        assert "chapter_added: 1" in body
        assert "section_added: /us/usc/t9/s1" in body
        assert "section_added: /us/usc/t9/s2" in body
        assert "section_added: /us/usc/t9/s3" in body
        assert "section_added: /us/usc/t9/s4" in body

    def test_first_commit_s4_attribution(self, git_commits):
        body = git_commits[0]["body"]
        s4_line = [l for l in body.split("\n")
                   if "section_added: /us/usc/t9/s4" in l]
        assert len(s4_line) == 1, "Should have exactly one s4 addition line"
        assert "116" in s4_line[0] and "150" in s4_line[0], (
            f"s4 should be attributed to Pub. L. 116-150: {s4_line[0]}"
        )

    def test_second_commit_changes(self, git_commits):
        body = git_commits[1]["body"]
        assert "Changes:" in body
        assert "section_amended: /us/usc/t9/s4" in body
        assert "117" in body and "81" in body

    def test_third_commit_changes(self, git_commits):
        body = git_commits[2]["body"]
        assert "Changes:" in body
        assert "section_amended: /us/usc/t9/s2" in body
        assert "chapter_added: 4" in body
        assert "section_added: /us/usc/t9/s401" in body
        assert "section_added: /us/usc/t9/s402" in body

    def test_third_commit_attribution(self, git_commits):
        body = git_commits[2]["body"]
        s2_line = [l for l in body.split("\n")
                   if "section_amended: /us/usc/t9/s2" in l]
        assert len(s2_line) == 1
        assert "117" in s2_line[0] and "90" in s2_line[0], (
            f"s2 amendment should be attributed to Pub. L. 117-90: {s2_line[0]}"
        )

    def test_fourth_commit_repeal(self, git_commits):
        body = git_commits[3]["body"]
        assert "Changes:" in body
        assert "section_repealed: /us/usc/t9/s4" in body

    def test_fourth_commit_s402_amendment(self, git_commits):
        body = git_commits[3]["body"]
        assert "section_amended: /us/usc/t9/s402" in body

    def test_fourth_commit_repeal_attribution(self, git_commits):
        body = git_commits[3]["body"]
        s4_line = [l for l in body.split("\n")
                   if "section_repealed: /us/usc/t9/s4" in l]
        assert len(s4_line) == 1
        assert "118" in s4_line[0] and "12" in s4_line[0], (
            f"s4 repeal should be attributed to Pub. L. 118-12: {s4_line[0]}"
        )


# ---------------------------------------------------------------------------
# 4. Git Tags
# ---------------------------------------------------------------------------

class TestGitTags:
    def test_annual_2021_exists(self, run_pipeline):
        tags = git_check(["tag", "--list"]).split("\n")
        assert "annual/2021" in tags

    def test_annual_2022_exists(self, run_pipeline):
        tags = git_check(["tag", "--list"]).split("\n")
        assert "annual/2022" in tags

    def test_annual_2024_exists(self, run_pipeline):
        tags = git_check(["tag", "--list"]).split("\n")
        assert "annual/2024" in tags

    def test_congress_116_exists(self, run_pipeline):
        tags = git_check(["tag", "--list"]).split("\n")
        assert "congress/116" in tags

    def test_congress_117_exists(self, run_pipeline):
        tags = git_check(["tag", "--list"]).split("\n")
        assert "congress/117" in tags

    def test_no_congress_118(self, run_pipeline):
        tags = git_check(["tag", "--list"]).split("\n")
        assert "congress/118" not in tags, (
            "congress/118 should not exist: 118-82 is not a boundary"
        )

    def test_annual_2021_on_second_commit(self, git_commits):
        """Two vintages share year 2021; the tag goes on the later one."""
        tag_commit = git_check(["rev-parse", "annual/2021"])
        assert tag_commit == git_commits[1]["hash"], (
            "annual/2021 should point to 2nd commit (117-81), not 1st (116-344)"
        )

    def test_annual_2021_not_on_first_commit(self, git_commits):
        tag_commit = git_check(["rev-parse", "annual/2021"])
        assert tag_commit != git_commits[0]["hash"], (
            "annual/2021 should NOT be on first commit (116-344)"
        )

    def test_congress_116_on_first_commit(self, git_commits):
        tag_commit = git_check(["rev-parse", "congress/116"])
        assert tag_commit == git_commits[0]["hash"]

    def test_congress_117_on_third_commit(self, git_commits):
        tag_commit = git_check(["rev-parse", "congress/117"])
        assert tag_commit == git_commits[2]["hash"]

    def test_annual_2022_on_third_commit(self, git_commits):
        tag_commit = git_check(["rev-parse", "annual/2022"])
        assert tag_commit == git_commits[2]["hash"]

    def test_annual_2024_on_fourth_commit(self, git_commits):
        tag_commit = git_check(["rev-parse", "annual/2024"])
        assert tag_commit == git_commits[3]["hash"]


# ---------------------------------------------------------------------------
# 5. Working Tree — Markdown Content
# ---------------------------------------------------------------------------

class TestMarkdownContent:
    def test_title_dir_exists(self, run_pipeline):
        assert os.path.isdir(os.path.join(REPO_DIR, "title-09"))

    def test_chapter1_file_exists(self, run_pipeline):
        files = os.listdir(os.path.join(REPO_DIR, "title-09"))
        chapter_files = [f for f in files if f.startswith("chapter-")]
        assert any("001" in f for f in chapter_files), (
            f"No chapter-001 file found: {files}"
        )

    def test_chapter4_file_exists(self, run_pipeline):
        files = os.listdir(os.path.join(REPO_DIR, "title-09"))
        chapter_files = [f for f in files if f.startswith("chapter-")]
        assert any("004" in f for f in chapter_files), (
            f"No chapter-004 file found: {files}"
        )

    def test_title_index_exists(self, run_pipeline):
        assert os.path.exists(
            os.path.join(REPO_DIR, "title-09", "title-index.md")
        )

    def test_chapter1_frontmatter(self, run_pipeline):
        title_dir = os.path.join(REPO_DIR, "title-09")
        files = [f for f in os.listdir(title_dir)
                 if "001" in f and f.startswith("chapter-")]
        assert len(files) >= 1
        content = open(os.path.join(title_dir, files[0])).read()
        fm = parse_frontmatter(content)
        assert fm["title"] == 9
        assert str(fm["chapter"]) == "1"
        assert fm["heading"] == "GENERAL PROVISIONS"

    def test_chapter1_section_count(self, run_pipeline):
        """Chapter 1 should count all 4 sections, including the repealed one."""
        title_dir = os.path.join(REPO_DIR, "title-09")
        files = [f for f in os.listdir(title_dir)
                 if "001" in f and f.startswith("chapter-")]
        content = open(os.path.join(title_dir, files[0])).read()
        fm = parse_frontmatter(content)
        assert fm["section_count"] == 4

    def test_chapter4_frontmatter(self, run_pipeline):
        title_dir = os.path.join(REPO_DIR, "title-09")
        files = [f for f in os.listdir(title_dir)
                 if "004" in f and f.startswith("chapter-")]
        assert len(files) >= 1
        content = open(os.path.join(title_dir, files[0])).read()
        fm = parse_frontmatter(content)
        assert fm["title"] == 9
        assert str(fm["chapter"]) == "4"
        assert fm["section_count"] == 2

    def test_repealed_section_heading(self, run_pipeline):
        """Section 4 heading should include [Repealed]."""
        title_dir = os.path.join(REPO_DIR, "title-09")
        files = [f for f in os.listdir(title_dir)
                 if "001" in f and f.startswith("chapter-")]
        body = get_body(open(os.path.join(title_dir, files[0])).read())
        assert "[Repealed]" in body, (
            "Chapter 1 should show [Repealed] for section 4"
        )

    def test_repealed_section_content(self, run_pipeline):
        """Section 4 repeal note should be rendered."""
        title_dir = os.path.join(REPO_DIR, "title-09")
        files = [f for f in os.listdir(title_dir)
                 if "001" in f and f.startswith("chapter-")]
        body = get_body(open(os.path.join(title_dir, files[0])).read())
        assert "repealed" in body.lower() and "118" in body

    def test_section_anchors(self, run_pipeline):
        title_dir = os.path.join(REPO_DIR, "title-09")
        files = [f for f in os.listdir(title_dir)
                 if "001" in f and f.startswith("chapter-")]
        body = get_body(open(os.path.join(title_dir, files[0])).read())
        assert '<a id="section-1"></a>' in body
        assert '<a id="section-2"></a>' in body
        assert '<a id="section-3"></a>' in body
        assert '<a id="section-4"></a>' in body

    def test_crossref_in_section2(self, run_pipeline):
        title_dir = os.path.join(REPO_DIR, "title-09")
        files = [f for f in os.listdir(title_dir)
                 if "001" in f and f.startswith("chapter-")]
        body = get_body(open(os.path.join(title_dir, files[0])).read())
        assert re.search(
            r"\[chapter 4\]\(https://uscode\.house\.gov/view\.xhtml\?"
            r"req=granuleid:USC-prelim-title9-section401",
            body,
        ), "Cross-ref to chapter 4 should be rewritten to uscode.house.gov"

    def test_crossref_to_title42(self, run_pipeline):
        title_dir = os.path.join(REPO_DIR, "title-09")
        files = [f for f in os.listdir(title_dir)
                 if "004" in f and f.startswith("chapter-")]
        body = get_body(open(os.path.join(title_dir, files[0])).read())
        assert re.search(
            r"\[section 12112 of title 42\]\(https://uscode\.house\.gov/",
            body,
        ), "Cross-ref to title 42 should be rewritten"

    def test_chapter4_subsection_labels_bold(self, run_pipeline):
        title_dir = os.path.join(REPO_DIR, "title-09")
        files = [f for f in os.listdir(title_dir)
                 if "004" in f and f.startswith("chapter-")]
        body = get_body(open(os.path.join(title_dir, files[0])).read())
        assert re.search(r"\*\*\(a\)", body), (
            "Subsection (a) label should be bold"
        )

    def test_statutory_notes_in_section2(self, run_pipeline):
        title_dir = os.path.join(REPO_DIR, "title-09")
        files = [f for f in os.listdir(title_dir)
                 if "001" in f and f.startswith("chapter-")]
        body = get_body(open(os.path.join(title_dir, files[0])).read())
        assert "### Statutory Notes" in body
        assert "#### Amendments" in body

    def test_title_index_frontmatter(self, run_pipeline):
        content = open(
            os.path.join(REPO_DIR, "title-09", "title-index.md")
        ).read()
        fm = parse_frontmatter(content)
        assert fm["title"] == 9
        assert fm["heading"] == "Arbitration"
        assert fm.get("positive_law") is True

    def test_title_index_lists_chapters(self, run_pipeline):
        body = get_body(
            open(os.path.join(REPO_DIR, "title-09", "title-index.md")).read()
        )
        assert "GENERAL PROVISIONS" in body
        assert "ARBITRATION OF DISPUTES" in body

    def test_no_raw_xml_in_output(self, run_pipeline):
        title_dir = os.path.join(REPO_DIR, "title-09")
        for f in os.listdir(title_dir):
            if f.endswith(".md"):
                body = get_body(open(os.path.join(title_dir, f)).read())
                cleaned = re.sub(r'<a id="[^"]+"></a>', "", body)
                assert not re.search(r"<(?!a\s)[a-zA-Z]", cleaned), (
                    f"Raw XML found in {f}"
                )


# ---------------------------------------------------------------------------
# 6. Content Evolution Across Commits
# ---------------------------------------------------------------------------

class TestContentEvolution:
    def test_first_commit_has_one_chapter(self, git_commits):
        tree = git_check(["ls-tree", "-r", "--name-only", git_commits[0]["hash"]])
        chapter_files = [
            f for f in tree.strip().split("\n")
            if f.startswith("title-09/chapter-")
        ]
        assert len(chapter_files) == 1, (
            f"First commit should have 1 chapter file, got: {chapter_files}"
        )

    def test_first_commit_four_sections(self, git_commits):
        """116-344 should have 4 sections in chapter 1."""
        tree = git_check(["ls-tree", "-r", "--name-only", git_commits[0]["hash"]])
        ch_files = [f for f in tree.strip().split("\n")
                    if f.startswith("title-09/chapter-") and "001" in f]
        assert len(ch_files) == 1
        content = git_check(["show", f"{git_commits[0]['hash']}:{ch_files[0]}"])
        fm = parse_frontmatter(content)
        assert fm["section_count"] == 4

    def test_third_commit_has_two_chapters(self, git_commits):
        tree = git_check(["ls-tree", "-r", "--name-only", git_commits[2]["hash"]])
        chapter_files = [
            f for f in tree.strip().split("\n")
            if f.startswith("title-09/chapter-")
        ]
        assert len(chapter_files) == 2, (
            f"Third commit should have 2 chapter files, got: {chapter_files}"
        )

    def test_second_commit_no_crossref_in_s2(self, git_commits):
        """Section 2 in vintage 117-81 should NOT have cross-ref to chapter 4."""
        tree = git_check(["ls-tree", "-r", "--name-only", git_commits[1]["hash"]])
        ch_files = [f for f in tree.strip().split("\n")
                    if f.startswith("title-09/chapter-") and "001" in f]
        content = git_check(["show", f"{git_commits[1]['hash']}:{ch_files[0]}"])
        body = get_body(content)
        assert "[chapter 4]" not in body, (
            "117-81 section 2 should not have cross-ref to chapter 4"
        )

    def test_third_commit_has_crossref_in_s2(self, git_commits):
        """Section 2 in vintage 117-262 SHOULD have cross-ref to chapter 4."""
        tree = git_check(["ls-tree", "-r", "--name-only", git_commits[2]["hash"]])
        ch_files = [f for f in tree.strip().split("\n")
                    if f.startswith("title-09/chapter-") and "001" in f]
        content = git_check(["show", f"{git_commits[2]['hash']}:{ch_files[0]}"])
        assert "uscode.house.gov" in content and "chapter 4" in content

    def test_fourth_commit_repealed_section(self, git_commits):
        """In vintage 118-82, section 4 should be marked repealed."""
        tree = git_check(["ls-tree", "-r", "--name-only", git_commits[3]["hash"]])
        ch_files = [f for f in tree.strip().split("\n")
                    if f.startswith("title-09/chapter-") and "001" in f]
        content = git_check(["show", f"{git_commits[3]['hash']}:{ch_files[0]}"])
        assert "[Repealed]" in content


# ---------------------------------------------------------------------------
# 7. Amendment Provenance
# ---------------------------------------------------------------------------

class TestAmendmentProvenance:
    def test_provenance_file_exists(self, provenance):
        assert isinstance(provenance, dict)

    def test_all_sections_present(self, provenance):
        expected = {
            "/us/usc/t9/s1", "/us/usc/t9/s2", "/us/usc/t9/s3",
            "/us/usc/t9/s4", "/us/usc/t9/s401", "/us/usc/t9/s402",
        }
        assert set(provenance.keys()) == expected, (
            f"Provenance keys: {set(provenance.keys())}"
        )

    def test_section1_no_pub_laws(self, provenance):
        entry = provenance["/us/usc/t9/s1"]
        assert entry["public_laws"] == [], (
            f"s1 should have no Pub. L. refs: {entry['public_laws']}"
        )
        assert entry["status"] == "in-force"

    def test_section2_pub_laws(self, provenance):
        entry = provenance["/us/usc/t9/s2"]
        pls = entry["public_laws"]
        assert len(pls) == 1, f"s2 should have 1 Pub. L.: {pls}"
        assert "117" in pls[0] and "90" in pls[0]
        assert entry["status"] == "in-force"

    def test_section3_no_pub_laws(self, provenance):
        entry = provenance["/us/usc/t9/s3"]
        assert entry["public_laws"] == []
        assert entry["status"] == "in-force"

    def test_section4_repealed_status(self, provenance):
        entry = provenance["/us/usc/t9/s4"]
        assert entry["status"] == "repealed"

    def test_section4_pub_laws(self, provenance):
        entry = provenance["/us/usc/t9/s4"]
        pls = entry["public_laws"]
        assert len(pls) == 3, f"s4 should have 3 Pub. L. refs: {pls}"
        pl_nums = " ".join(pls)
        assert "116" in pl_nums and "150" in pl_nums
        assert "117" in pl_nums and "81" in pl_nums
        assert "118" in pl_nums and "12" in pl_nums

    def test_section4_heading_includes_repealed(self, provenance):
        entry = provenance["/us/usc/t9/s4"]
        assert "[Repealed]" in entry["heading"]

    def test_section401_pub_laws(self, provenance):
        entry = provenance["/us/usc/t9/s401"]
        pls = entry["public_laws"]
        assert len(pls) == 1
        assert "117" in pls[0] and "90" in pls[0]

    def test_section402_pub_laws(self, provenance):
        entry = provenance["/us/usc/t9/s402"]
        pls = entry["public_laws"]
        assert len(pls) == 2, f"s402 should have 2 Pub. L. refs: {pls}"
        pl_text = " ".join(pls)
        assert "117" in pl_text and "90" in pl_text
        assert "118" in pl_text and "63" in pl_text

    def test_first_appeared_original_sections(self, provenance):
        for sid in ["/us/usc/t9/s1", "/us/usc/t9/s2",
                    "/us/usc/t9/s3", "/us/usc/t9/s4"]:
            assert provenance[sid]["first_appeared"] == "116-344", (
                f"{sid} should first appear in 116-344"
            )

    def test_first_appeared_chapter4_sections(self, provenance):
        for sid in ["/us/usc/t9/s401", "/us/usc/t9/s402"]:
            assert provenance[sid]["first_appeared"] == "117-262", (
                f"{sid} should first appear in 117-262"
            )

    def test_provenance_entry_fields(self, provenance):
        for sid, entry in provenance.items():
            assert "heading" in entry, f"{sid} missing heading"
            assert "status" in entry, f"{sid} missing status"
            assert "public_laws" in entry, f"{sid} missing public_laws"
            assert "first_appeared" in entry, f"{sid} missing first_appeared"
            assert isinstance(entry["public_laws"], list)


# ---------------------------------------------------------------------------
# 8. Cross-Reference Analysis
# ---------------------------------------------------------------------------

class TestCrossRefAnalysis:
    def test_xref_file_exists(self, xref_analysis):
        assert "summary" in xref_analysis
        assert "references" in xref_analysis

    def test_summary_intra_title(self, xref_analysis):
        assert xref_analysis["summary"]["intra_title"] == 2, (
            f"Expected 2 intra_title refs: {xref_analysis['summary']}"
        )

    def test_summary_inter_title(self, xref_analysis):
        assert xref_analysis["summary"]["inter_title"] == 1, (
            f"Expected 1 inter_title ref: {xref_analysis['summary']}"
        )

    def test_summary_dangling(self, xref_analysis):
        assert xref_analysis["summary"]["dangling"] == 1, (
            f"Expected 1 dangling ref: {xref_analysis['summary']}"
        )

    def test_total_reference_count(self, xref_analysis):
        refs = xref_analysis["references"]
        assert len(refs) == 4, f"Expected 4 references, got {len(refs)}"

    def test_s2_to_s401_intra(self, xref_analysis):
        matching = [r for r in xref_analysis["references"]
                    if r["source"] == "/us/usc/t9/s2"
                    and r["target"] == "/us/usc/t9/s401"]
        assert len(matching) == 1, "Missing s2->s401 reference"
        assert matching[0]["classification"] == "intra_title"
        assert "chapter 4" in matching[0]["link_text"]

    def test_s402_to_t42_inter(self, xref_analysis):
        matching = [r for r in xref_analysis["references"]
                    if r["source"] == "/us/usc/t9/s402"
                    and r["target"] == "/us/usc/t42/s12112"]
        assert len(matching) == 1, "Missing s402->t42/s12112 reference"
        assert matching[0]["classification"] == "inter_title"

    def test_s402_to_s2_intra(self, xref_analysis):
        matching = [r for r in xref_analysis["references"]
                    if r["source"] == "/us/usc/t9/s402"
                    and r["target"] == "/us/usc/t9/s2"]
        assert len(matching) == 1, "Missing s402->s2 reference"
        assert matching[0]["classification"] == "intra_title"

    def test_s402_to_t53_dangling(self, xref_analysis):
        matching = [r for r in xref_analysis["references"]
                    if r["source"] == "/us/usc/t9/s402"
                    and r["target"] == "/us/usc/t53/s3001"]
        assert len(matching) == 1, "Missing s402->t53/s3001 dangling reference"
        assert matching[0]["classification"] == "dangling"

    def test_no_refs_from_repealed_s4(self, xref_analysis):
        s4_refs = [r for r in xref_analysis["references"]
                   if r["source"] == "/us/usc/t9/s4"]
        assert len(s4_refs) == 0, (
            f"Repealed s4 should have no refs in latest vintage: {s4_refs}"
        )

    def test_reference_fields(self, xref_analysis):
        for ref in xref_analysis["references"]:
            assert "source" in ref
            assert "target" in ref
            assert "link_text" in ref
            assert "classification" in ref


# ---------------------------------------------------------------------------
# 9. Structural Changelog
# ---------------------------------------------------------------------------

class TestStructuralChangelog:
    def test_changelog_file_exists(self, changelog):
        assert isinstance(changelog, list)

    def test_three_diff_entries(self, changelog):
        assert len(changelog) == 3, (
            f"Expected 3 changelog entries, got {len(changelog)}"
        )

    def test_first_diff_vintage_pair(self, changelog):
        assert changelog[0]["from_vintage"] == "116-344"
        assert changelog[0]["to_vintage"] == "117-81"

    def test_first_diff_changes(self, changelog):
        changes = changelog[0]["changes"]
        types = {c["type"] for c in changes}
        ids = {c["identifier"] for c in changes}
        assert "section_amended" in types
        assert "/us/usc/t9/s4" in ids
        assert len(changes) == 1, (
            f"First diff should have 1 change, got {len(changes)}: {changes}"
        )

    def test_first_diff_attribution(self, changelog):
        changes = changelog[0]["changes"]
        s4_change = [c for c in changes
                     if c["identifier"] == "/us/usc/t9/s4"][0]
        attr = s4_change.get("attribution", "")
        assert attr is not None and "117" in attr and "81" in attr, (
            f"s4 amendment should be attributed to Pub. L. 117-81: {attr}"
        )

    def test_second_diff_vintage_pair(self, changelog):
        assert changelog[1]["from_vintage"] == "117-81"
        assert changelog[1]["to_vintage"] == "117-262"

    def test_second_diff_changes(self, changelog):
        changes = changelog[1]["changes"]
        types = {c["type"] for c in changes}
        ids = {c["identifier"] for c in changes}
        assert "section_amended" in types
        assert "chapter_added" in types
        assert "section_added" in types
        assert "/us/usc/t9/s2" in ids
        assert "/us/usc/t9/s401" in ids
        assert "/us/usc/t9/s402" in ids
        assert len(changes) == 4, (
            f"Second diff should have 4 changes, got {len(changes)}: {changes}"
        )

    def test_third_diff_vintage_pair(self, changelog):
        assert changelog[2]["from_vintage"] == "117-262"
        assert changelog[2]["to_vintage"] == "118-82"

    def test_third_diff_changes(self, changelog):
        changes = changelog[2]["changes"]
        types = {c["type"] for c in changes}
        ids = {c["identifier"] for c in changes}
        assert "section_repealed" in types
        assert "section_amended" in types
        assert "/us/usc/t9/s4" in ids
        assert "/us/usc/t9/s402" in ids
        assert len(changes) == 2, (
            f"Third diff should have 2 changes, got {len(changes)}: {changes}"
        )

    def test_third_diff_repeal_attribution(self, changelog):
        changes = changelog[2]["changes"]
        s4_change = [c for c in changes
                     if c["identifier"] == "/us/usc/t9/s4"][0]
        assert s4_change["type"] == "section_repealed"
        attr = s4_change.get("attribution", "")
        assert attr is not None and "118" in attr and "12" in attr

    def test_third_diff_amendment_attribution(self, changelog):
        changes = changelog[2]["changes"]
        s402_change = [c for c in changes
                       if c["identifier"] == "/us/usc/t9/s402"][0]
        assert s402_change["type"] == "section_amended"
        attr = s402_change.get("attribution", "")
        assert attr is not None and "118" in attr and "63" in attr

    def test_changelog_entry_fields(self, changelog):
        for entry in changelog:
            assert "from_vintage" in entry
            assert "to_vintage" in entry
            assert "changes" in entry
            for change in entry["changes"]:
                assert "type" in change
                assert "identifier" in change
                assert "attribution" in change or change.get("attribution") is None


# ---------------------------------------------------------------------------
# 10. Fast-Import Stream
# ---------------------------------------------------------------------------

class TestFastImportStream:
    def test_stream_file_exists(self, run_pipeline):
        path = os.path.join(OUTPUT_DIR, "fast-import.stream")
        assert os.path.exists(path)

    def test_stream_four_commit_directives(self, run_pipeline):
        path = os.path.join(OUTPUT_DIR, "fast-import.stream")
        content = open(path).read()
        assert content.count("commit refs/heads/main") == 4, (
            "Stream should contain exactly 4 commit directives"
        )

    def test_stream_contains_inline_blobs(self, run_pipeline):
        path = os.path.join(OUTPUT_DIR, "fast-import.stream")
        content = open(path).read()
        assert "M 100644 inline" in content

    def test_stream_has_correct_timestamps(self, run_pipeline):
        path = os.path.join(OUTPUT_DIR, "fast-import.stream")
        content = open(path).read()
        # 2021-01-03T00:00:00 UTC = 1609632000
        assert "1609632000" in content, (
            "Stream should contain timestamp for 2021-01-03"
        )
        # 2021-11-15T00:00:00 UTC = 1636934400
        assert "1636934400" in content, (
            "Stream should contain timestamp for 2021-11-15"
        )
