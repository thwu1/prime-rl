
import subprocess
import os
import json
import tempfile
import textwrap

FREDBUF_DIR = "/app/fredbuf"
BUILD_DIR = os.path.join(FREDBUF_DIR, "build")


def run_cmd(cmd, cwd=None, timeout=60):
    result = subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True, timeout=timeout
    )
    return result


def build_project():
    """Build the fredbuf library and test binary."""
    os.makedirs(BUILD_DIR, exist_ok=True)
    r = run_cmd("cmake .. -DCMAKE_BUILD_TYPE=Release", cwd=BUILD_DIR, timeout=30)
    assert r.returncode == 0, f"CMake configure failed:\n{r.stderr}"
    r = run_cmd("cmake --build . --parallel", cwd=BUILD_DIR, timeout=120)
    assert r.returncode == 0, f"CMake build failed:\n{r.stderr}"


def build_and_run_test_program(source_code, extra_link=""):
    """Compile a test .cpp against libfredbuf.a and run it."""
    with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, dir=BUILD_DIR) as f:
        f.write(source_code)
        src_path = f.name

    bin_path = src_path.replace(".cpp", "")
    include_dir = os.path.join(FREDBUF_DIR, "include")
    lib_path = os.path.join(BUILD_DIR, "libfredbuf.a")

    compile_cmd = (
        f"g++ -std=c++20 -O2 -I{include_dir} {src_path} {lib_path} "
        f"-o {bin_path} {extra_link}"
    )
    r = run_cmd(compile_cmd, cwd=BUILD_DIR, timeout=30)
    assert r.returncode == 0, f"Compilation failed:\n{r.stderr}\nSource:\n{source_code[:500]}"

    r = run_cmd(bin_path, cwd=BUILD_DIR, timeout=30)
    os.unlink(src_path)
    if os.path.exists(bin_path):
        os.unlink(bin_path)
    return r


class TestBuildAndHeaders:
    """Test that the project builds and headers are present."""

    def test_build(self):
        build_project()

    def test_headers_exist(self):
        inc = os.path.join(FREDBUF_DIR, "include", "fredbuf")
        assert os.path.isfile(os.path.join(inc, "piece_table.h"))
        assert os.path.isfile(os.path.join(inc, "undo_tree.h"))
        assert os.path.isfile(os.path.join(inc, "myers_diff.h"))

    def test_static_library_exists(self):
        build_project()
        assert os.path.isfile(os.path.join(BUILD_DIR, "libfredbuf.a"))


class TestPieceTableBasics:
    """Test basic piece table insert/erase/text operations."""

    def test_insert_and_read(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/piece_table.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::PieceTable pt;
            pt.insert(0, "Hello");
            pt.insert(5, " World");
            pt.insert(11, "!");
            std::string t = pt.text();
            assert(t == "Hello World!");
            std::cout << "OK insert_and_read" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK insert_and_read" in r.stdout

    def test_erase(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/piece_table.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::PieceTable pt;
            pt.insert(0, "Hello World!");
            pt.erase(5, 6);  // erase " World"  (offset=5, length=6) -> "Hello!"
            std::string t = pt.text();
            assert(t == "Hello!");
            std::cout << "OK erase" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK erase" in r.stdout

    def test_length(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/piece_table.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::PieceTable pt;
            pt.insert(0, "abcdef");
            assert(pt.length() == 6);
            pt.erase(2, 2);  // remove "cd"
            assert(pt.length() == 4);
            assert(pt.text() == "abef");
            std::cout << "OK length" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK length" in r.stdout

    def test_line_operations(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/piece_table.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::PieceTable pt;
            pt.insert(0, "line1\nline2\nline3\n");
            assert(pt.line_count() >= 3);
            std::string l1 = pt.line_at(0);
            assert(l1 == "line1" || l1 == "line1\n");
            std::cout << "OK line_operations" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK line_operations" in r.stdout

    def test_insert_middle(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/piece_table.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::PieceTable pt;
            pt.insert(0, "Helo");
            pt.insert(2, "l");  // insert 'l' at position 2
            assert(pt.text() == "Hello");
            pt.insert(5, " World");
            assert(pt.text() == "Hello World");
            std::cout << "OK insert_middle" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK insert_middle" in r.stdout

    def test_multiple_erases(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/piece_table.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::PieceTable pt;
            pt.insert(0, "abcdefghij");
            pt.erase(7, 3);  // remove "hij" -> "abcdefg"
            pt.erase(0, 3);  // remove "abc" -> "defg"
            pt.erase(1, 2);  // remove "ef" -> "dg"
            assert(pt.text() == "dg");
            std::cout << "OK multiple_erases" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK multiple_erases" in r.stdout


class TestPersistence:
    """Test that the piece table is truly persistent (old snapshots survive)."""

    def test_snapshot_persistence(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/piece_table.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::PieceTable pt;
            pt.insert(0, "Hello");
            auto snap1 = pt.snapshot_id();

            pt.insert(5, " World");
            auto snap2 = pt.snapshot_id();

            // The piece table must be persistent: old snapshots remain accessible
            // We verify this through the undo_tree which uses snapshot_id
            // Here we just verify snapshot_id changes
            assert(snap1 != snap2);
            assert(pt.text() == "Hello World");
            std::cout << "OK snapshot_persistence" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK snapshot_persistence" in r.stdout


class TestUndoTree:
    """Test branching undo/redo tree."""

    def test_basic_undo(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/undo_tree.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::UndoTree ut;
            ut.insert(0, "Hello");
            ut.commit();
            ut.insert(5, " World");
            ut.commit();
            assert(ut.text() == "Hello World");

            ut.undo();
            assert(ut.text() == "Hello");

            ut.undo();
            assert(ut.text() == "");

            std::cout << "OK basic_undo" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK basic_undo" in r.stdout

    def test_basic_redo(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/undo_tree.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::UndoTree ut;
            ut.insert(0, "A");
            ut.commit();
            ut.insert(1, "B");
            ut.commit();

            ut.undo();
            assert(ut.text() == "A");
            ut.redo(0);
            assert(ut.text() == "AB");

            std::cout << "OK basic_redo" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK basic_redo" in r.stdout

    def test_branching_undo(self):
        """After undo + new edit, old redo branch preserved."""
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/undo_tree.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::UndoTree ut;

            // State 0: ""
            ut.insert(0, "Hello");
            ut.commit();
            // State 1: "Hello"
            auto s1 = ut.current_snapshot_id();

            ut.insert(5, " World");
            ut.commit();
            // State 2: "Hello World"
            auto s2 = ut.current_snapshot_id();

            // Undo back to "Hello"
            ut.undo();
            assert(ut.text() == "Hello");

            // Now branch: insert different text
            ut.insert(5, " Cameron");
            ut.commit();
            // State 3: "Hello Cameron"
            auto s3 = ut.current_snapshot_id();
            assert(ut.text() == "Hello Cameron");

            // The branch at state 1 should have 2 children
            auto branches = ut.branches_at(s1);
            assert(branches >= 2);

            // We should be able to checkout s2 and get "Hello World"
            ut.checkout(s2);
            assert(ut.text() == "Hello World");

            // And checkout s3 and get "Hello Cameron"
            ut.checkout(s3);
            assert(ut.text() == "Hello Cameron");

            std::cout << "OK branching_undo" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK branching_undo" in r.stdout

    def test_history_node_count(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/undo_tree.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::UndoTree ut;
            assert(ut.history_node_count() >= 1);  // at least root

            ut.insert(0, "A");
            ut.commit();
            ut.insert(1, "B");
            ut.commit();
            ut.insert(2, "C");
            ut.commit();
            assert(ut.history_node_count() >= 4);  // root + 3 commits

            std::cout << "OK history_node_count" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK history_node_count" in r.stdout

    def test_text_at_snapshot(self):
        """text_at(id) retrieves text for any historical snapshot."""
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/undo_tree.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::UndoTree ut;
            auto s0 = ut.current_snapshot_id();

            ut.insert(0, "alpha");
            ut.commit();
            auto s1 = ut.current_snapshot_id();

            ut.insert(5, " beta");
            ut.commit();
            auto s2 = ut.current_snapshot_id();

            // Check historical text without changing current state
            assert(ut.text_at(s0) == "");
            assert(ut.text_at(s1) == "alpha");
            assert(ut.text_at(s2) == "alpha beta");

            // Current state should still be s2
            assert(ut.text() == "alpha beta");

            std::cout << "OK text_at_snapshot" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK text_at_snapshot" in r.stdout


class TestMyersDiff:
    """Test the Myers diff algorithm."""

    def test_simple_diff(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/myers_diff.h>
        #include <iostream>
        #include <cassert>
        int main() {
            auto hunks = fredbuf::myers_diff("Hello\n", "Hello World!\n");
            // Should contain at least one delete and one insert
            bool has_delete = false, has_insert = false;
            for (auto& h : hunks) {
                if (h.op == fredbuf::DiffHunk::Delete) has_delete = true;
                if (h.op == fredbuf::DiffHunk::Insert) has_insert = true;
            }
            assert(has_delete || has_insert);
            std::cout << "OK simple_diff" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK simple_diff" in r.stdout

    def test_identical_diff(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/myers_diff.h>
        #include <iostream>
        #include <cassert>
        int main() {
            auto hunks = fredbuf::myers_diff("same\n", "same\n");
            // All hunks should be Equal
            for (auto& h : hunks) {
                assert(h.op == fredbuf::DiffHunk::Equal);
            }
            assert(!hunks.empty());
            std::cout << "OK identical_diff" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK identical_diff" in r.stdout

    def test_multiline_diff(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/myers_diff.h>
        #include <iostream>
        #include <cassert>
        int main() {
            std::string old_text = "line1\nline2\nline3\n";
            std::string new_text = "line1\nmodified\nline3\nnew_line4\n";
            auto hunks = fredbuf::myers_diff(old_text, new_text);

            // Reconstruct old and new from hunks
            std::string reconstructed_old, reconstructed_new;
            for (auto& h : hunks) {
                if (h.op == fredbuf::DiffHunk::Equal) {
                    reconstructed_old += h.line + "\n";
                    reconstructed_new += h.line + "\n";
                } else if (h.op == fredbuf::DiffHunk::Delete) {
                    reconstructed_old += h.line + "\n";
                } else if (h.op == fredbuf::DiffHunk::Insert) {
                    reconstructed_new += h.line + "\n";
                }
            }
            assert(reconstructed_old == old_text);
            assert(reconstructed_new == new_text);

            std::cout << "OK multiline_diff" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK multiline_diff" in r.stdout

    def test_empty_diff(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/myers_diff.h>
        #include <iostream>
        #include <cassert>
        int main() {
            auto hunks = fredbuf::myers_diff("", "new_line\n");
            bool has_insert = false;
            for (auto& h : hunks) {
                if (h.op == fredbuf::DiffHunk::Insert) has_insert = true;
            }
            assert(has_insert);

            auto hunks2 = fredbuf::myers_diff("old_line\n", "");
            bool has_delete = false;
            for (auto& h : hunks2) {
                if (h.op == fredbuf::DiffHunk::Delete) has_delete = true;
            }
            assert(has_delete);

            std::cout << "OK empty_diff" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK empty_diff" in r.stdout


class TestRBTreeInvariants:
    """Verify RB tree properties are maintained."""

    def test_rb_invariants_after_operations(self):
        """Build stress test: many inserts and erases, verify text correctness."""
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/piece_table.h>
        #include <iostream>
        #include <cassert>
        #include <string>
        int main() {
            fredbuf::PieceTable pt;
            std::string expected;

            // Build up text character by character
            for (int i = 0; i < 200; i++) {
                char c = 'a' + (i % 26);
                std::string s(1, c);
                size_t pos = i / 2;  // insert near middle
                if (pos > expected.size()) pos = expected.size();
                pt.insert(pos, s);
                expected.insert(pos, s);
            }
            assert(pt.text() == expected);
            assert(pt.length() == expected.size());

            // Now erase every other character
            for (int i = 0; i < 50; i++) {
                size_t pos = i;
                if (pos >= expected.size()) break;
                pt.erase(pos, 1);
                expected.erase(pos, 1);
            }
            assert(pt.text() == expected);
            assert(pt.length() == expected.size());

            std::cout << "OK rb_invariants" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK rb_invariants" in r.stdout


class TestPathCopying:
    """Verify path-copying persistence: old roots stay valid."""

    def test_persistence_through_undo_tree(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/undo_tree.h>
        #include <iostream>
        #include <cassert>
        #include <vector>
        #include <string>
        int main() {
            fredbuf::UndoTree ut;
            std::vector<size_t> snapshots;
            std::vector<std::string> expected_texts;

            snapshots.push_back(ut.current_snapshot_id());
            expected_texts.push_back("");

            std::string current;
            for (int i = 0; i < 20; i++) {
                std::string chunk = "chunk" + std::to_string(i) + " ";
                ut.insert(current.size(), chunk);
                current += chunk;
                ut.commit();
                snapshots.push_back(ut.current_snapshot_id());
                expected_texts.push_back(current);
            }

            // Verify ALL old snapshots are still intact
            for (size_t i = 0; i < snapshots.size(); i++) {
                std::string actual = ut.text_at(snapshots[i]);
                assert(actual == expected_texts[i]);
            }

            std::cout << "OK persistence_through_undo_tree" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK persistence_through_undo_tree" in r.stdout


class TestIntegration:
    """Test that undo tree and diff work together."""

    def test_diff_between_snapshots(self):
        build_project()
        src = textwrap.dedent(r'''
        #include <fredbuf/undo_tree.h>
        #include <fredbuf/myers_diff.h>
        #include <iostream>
        #include <cassert>
        int main() {
            fredbuf::UndoTree ut;
            ut.insert(0, "line1\nline2\nline3\n");
            ut.commit();
            auto s1 = ut.current_snapshot_id();

            ut.erase(6, 5);  // remove "line2"
            ut.insert(6, "modified");
            ut.commit();
            auto s2 = ut.current_snapshot_id();

            auto old_text = ut.text_at(s1);
            auto new_text = ut.text_at(s2);

            auto hunks = fredbuf::myers_diff(old_text, new_text);

            // Reconstruct and verify
            std::string ro, rn;
            for (auto& h : hunks) {
                if (h.op == fredbuf::DiffHunk::Equal) {
                    ro += h.line + "\n";
                    rn += h.line + "\n";
                } else if (h.op == fredbuf::DiffHunk::Delete) {
                    ro += h.line + "\n";
                } else {
                    rn += h.line + "\n";
                }
            }
            assert(ro == old_text);
            assert(rn == new_text);

            std::cout << "OK diff_between_snapshots" << std::endl;
            return 0;
        }
        ''')
        r = build_and_run_test_program(src)
        assert r.returncode == 0, f"Failed:\n{r.stdout}\n{r.stderr}"
        assert "OK diff_between_snapshots" in r.stdout
