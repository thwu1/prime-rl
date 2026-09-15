#pragma once

#include <string>
#include <memory>
#include <vector>
#include <cstddef>

namespace fredbuf {

// Persistent red-black tree node for the piece table
enum class Color { Red, Black, DoubleBlack };

struct Piece {
    size_t buffer_id;   // 0 = original, 1+ = add buffers
    size_t start;
    size_t length;
};

struct RBNode;
using RBNodePtr = std::shared_ptr<const RBNode>;

struct RBNode {
    Color color;
    RBNodePtr left;
    RBNodePtr right;
    Piece piece;
    size_t subtree_size;  // total chars in this subtree

    RBNode(Color c, RBNodePtr l, RBNodePtr r, Piece p, size_t sz)
        : color(c), left(std::move(l)), right(std::move(r)),
          piece(p), subtree_size(sz) {}
};

// Helper functions for persistent RB tree
RBNodePtr rb_insert(const RBNodePtr& root, size_t offset, const Piece& piece);
RBNodePtr rb_erase(const RBNodePtr& root, size_t offset, size_t length);
std::string rb_text(const RBNodePtr& root, const std::vector<std::string>& buffers);
size_t rb_size(const RBNodePtr& node);

class PieceTable {
public:
    PieceTable();
    PieceTable(const std::string& initial_text);

    void insert(size_t offset, const std::string& text);
    void erase(size_t offset, size_t length);

    std::string text() const;
    size_t length() const;
    size_t line_count() const;
    std::string line_at(size_t line_index) const;

    size_t snapshot_id() const;

    // Internal: for undo tree
    RBNodePtr root() const { return root_; }
    void set_root(RBNodePtr r) { root_ = std::move(r); }
    const std::vector<std::string>& buffers() const { return buffers_; }
    std::vector<std::string>& buffers_mut() { return buffers_; }

private:
    std::vector<std::string> buffers_;  // buffer 0 = original, rest = add buffers
    RBNodePtr root_;
    size_t snapshot_counter_;
    size_t current_snapshot_;
};

} // namespace fredbuf
