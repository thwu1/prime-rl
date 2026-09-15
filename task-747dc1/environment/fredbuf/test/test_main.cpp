// Smoke test for fredbuf library
#include <fredbuf/piece_table.h>
#include <fredbuf/undo_tree.h>
#include <fredbuf/myers_diff.h>
#include <iostream>
#include <cassert>

int main() {
    // PieceTable basics
    {
        fredbuf::PieceTable pt;
        pt.insert(0, "Hello");
        pt.insert(5, " World!");
        assert(pt.text() == "Hello World!");
        assert(pt.length() == 12);

        pt.erase(5, 6);
        assert(pt.text() == "Hello!");
    }

    // UndoTree branching
    {
        fredbuf::UndoTree ut;
        ut.insert(0, "A");
        ut.commit();
        ut.insert(1, "B");
        ut.commit();
        assert(ut.text() == "AB");

        ut.undo();
        assert(ut.text() == "A");

        ut.redo(0);
        assert(ut.text() == "AB");
    }

    // Diff
    {
        auto hunks = fredbuf::myers_diff("hello\n", "hello\nworld\n");
        assert(!hunks.empty());
        bool has_insert = false;
        for (auto& h : hunks) {
            if (h.op == fredbuf::DiffHunk::Insert) has_insert = true;
        }
        assert(has_insert);
    }

    std::cout << "All smoke tests passed!" << std::endl;
    return 0;
}
