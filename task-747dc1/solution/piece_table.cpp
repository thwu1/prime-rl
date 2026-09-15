
#include <fredbuf/piece_table.h>
#include <algorithm>
#include <sstream>
#include <cassert>

namespace fredbuf {

// ============================================================
// Persistent Red-Black Tree operations
// ============================================================

size_t rb_size(const RBNodePtr& node) {
    return node ? node->subtree_size : 0;
}

static RBNodePtr make_node(Color c, RBNodePtr l, RBNodePtr r, Piece p) {
    size_t sz = p.length + rb_size(l) + rb_size(r);
    return std::make_shared<const RBNode>(c, std::move(l), std::move(r), p, sz);
}

static RBNodePtr recolor(const RBNodePtr& n, Color c) {
    if (!n) return nullptr;
    if (n->color == c) return n;
    return make_node(c, n->left, n->right, n->piece);
}

// Balance after insertion (Okasaki-style)
static RBNodePtr balance(Color c, RBNodePtr left, Piece piece, RBNodePtr right) {
    if (c == Color::Black) {
        // Case 1: left->left is red
        if (left && left->color == Color::Red &&
            left->left && left->left->color == Color::Red) {
            return make_node(Color::Red,
                recolor(left->left, Color::Black),
                make_node(Color::Black, left->right, right, piece),
                left->piece);
        }
        // Case 2: left->right is red
        if (left && left->color == Color::Red &&
            left->right && left->right->color == Color::Red) {
            return make_node(Color::Red,
                make_node(Color::Black, left->left, left->right->left, left->piece),
                make_node(Color::Black, left->right->right, right, piece),
                left->right->piece);
        }
        // Case 3: right->left is red
        if (right && right->color == Color::Red &&
            right->left && right->left->color == Color::Red) {
            return make_node(Color::Red,
                make_node(Color::Black, left, right->left->left, piece),
                make_node(Color::Black, right->left->right, right->right, right->piece),
                right->left->piece);
        }
        // Case 4: right->right is red
        if (right && right->color == Color::Red &&
            right->right && right->right->color == Color::Red) {
            return make_node(Color::Red,
                make_node(Color::Black, left, right->left, piece),
                recolor(right->right, Color::Black),
                right->piece);
        }
    }
    return make_node(c, left, right, piece);
}

// Insert a piece at a given character offset
static RBNodePtr rb_insert_impl(const RBNodePtr& node, size_t offset, const Piece& piece) {
    if (!node) {
        return make_node(Color::Red, nullptr, nullptr, piece);
    }

    size_t left_size = rb_size(node->left);

    if (offset <= left_size) {
        // If offset falls exactly at the start of this node's piece,
        // or within the left subtree
        if (offset == left_size) {
            // Insert before this node
            auto new_left = rb_insert_impl(node->left, offset, piece);
            return balance(node->color, new_left, node->piece, node->right);
        } else {
            auto new_left = rb_insert_impl(node->left, offset, piece);
            return balance(node->color, new_left, node->piece, node->right);
        }
    } else if (offset >= left_size + node->piece.length) {
        // Insert into right subtree
        auto new_right = rb_insert_impl(node->right, offset - left_size - node->piece.length, piece);
        return balance(node->color, node->left, node->piece, new_right);
    } else {
        // Offset falls within this node's piece — split the piece
        size_t split_pos = offset - left_size;
        Piece left_piece = { node->piece.buffer_id, node->piece.start, split_pos };
        Piece right_piece = { node->piece.buffer_id, node->piece.start + split_pos,
                              node->piece.length - split_pos };

        // Insert left_piece into left subtree at the end
        auto new_left = rb_insert_impl(node->left, left_size, left_piece);
        // The new piece goes after left_piece, which is now at position left_size + split_pos
        // We need to insert the new piece, then right_piece

        // First, create a node for the new piece
        auto mid = make_node(Color::Red, nullptr, nullptr, piece);

        // Now insert right_piece into right subtree at position 0
        auto new_right = rb_insert_impl(node->right, 0, right_piece);

        // We need to replace the current node. Use the new piece as the node value.
        return balance(node->color, new_left, piece, new_right);
    }
}

RBNodePtr rb_insert(const RBNodePtr& root, size_t offset, const Piece& piece) {
    auto result = rb_insert_impl(root, offset, piece);
    // Root must be black
    return recolor(result, Color::Black);
}

// Collect all pieces in order
static void collect_pieces(const RBNodePtr& node, std::vector<Piece>& out) {
    if (!node) return;
    collect_pieces(node->left, out);
    out.push_back(node->piece);
    collect_pieces(node->right, out);
}

// Build a balanced RB tree from a sorted list of pieces
static RBNodePtr build_tree(const std::vector<Piece>& pieces, size_t start, size_t end, int depth) {
    if (start >= end) return nullptr;
    size_t mid = start + (end - start) / 2;
    auto left = build_tree(pieces, start, mid, depth + 1);
    auto right = build_tree(pieces, mid + 1, end, depth + 1);
    Color c = (depth == 0) ? Color::Black : ((depth % 2 == 0) ? Color::Black : Color::Red);
    // Ensure no red-red violations: if children are red, this must be black
    if ((left && left->color == Color::Red) || (right && right->color == Color::Red)) {
        c = Color::Black;
    }
    return make_node(c, left, right, pieces[mid]);
}

static RBNodePtr rebuild_from_pieces(const std::vector<Piece>& pieces) {
    if (pieces.empty()) return nullptr;
    auto root = build_tree(pieces, 0, pieces.size(), 0);
    return recolor(root, Color::Black);
}

RBNodePtr rb_erase(const RBNodePtr& root, size_t offset, size_t erase_len) {
    if (!root || erase_len == 0) return root;

    // Collect all pieces, then rebuild excluding the erased range
    std::vector<Piece> pieces;
    collect_pieces(root, pieces);

    std::vector<Piece> new_pieces;
    size_t pos = 0;
    for (auto& p : pieces) {
        size_t p_start = pos;
        size_t p_end = pos + p.length;

        size_t erase_start = offset;
        size_t erase_end = offset + erase_len;

        if (p_end <= erase_start || p_start >= erase_end) {
            // No overlap
            new_pieces.push_back(p);
        } else {
            // Partial overlap
            if (p_start < erase_start) {
                // Keep left portion
                Piece left_part = { p.buffer_id, p.start, erase_start - p_start };
                new_pieces.push_back(left_part);
            }
            if (p_end > erase_end) {
                // Keep right portion
                size_t skip = erase_end - p_start;
                Piece right_part = { p.buffer_id, p.start + skip, p_end - erase_end };
                new_pieces.push_back(right_part);
            }
        }
        pos = p_end;
    }

    return rebuild_from_pieces(new_pieces);
}

std::string rb_text(const RBNodePtr& root, const std::vector<std::string>& buffers) {
    if (!root) return "";
    std::string result;
    result.reserve(root->subtree_size);

    // In-order traversal
    struct StackFrame {
        const RBNode* node;
        int state; // 0=go left, 1=process, 2=go right
    };
    std::vector<StackFrame> stack;
    if (root) stack.push_back({root.get(), 0});

    while (!stack.empty()) {
        auto& frame = stack.back();
        if (frame.state == 0) {
            frame.state = 1;
            if (frame.node->left) {
                stack.push_back({frame.node->left.get(), 0});
            }
        } else if (frame.state == 1) {
            frame.state = 2;
            auto& p = frame.node->piece;
            if (p.buffer_id < buffers.size() && p.length > 0) {
                result.append(buffers[p.buffer_id], p.start, p.length);
            }
            if (frame.node->right) {
                stack.push_back({frame.node->right.get(), 0});
            }
        } else {
            stack.pop_back();
        }
    }
    return result;
}

// ============================================================
// PieceTable implementation
// ============================================================

PieceTable::PieceTable()
    : snapshot_counter_(1), current_snapshot_(0) {
    buffers_.emplace_back(""); // original buffer (empty)
}

PieceTable::PieceTable(const std::string& initial_text)
    : snapshot_counter_(1), current_snapshot_(0) {
    buffers_.push_back(initial_text);
    if (!initial_text.empty()) {
        Piece p = { 0, 0, initial_text.size() };
        root_ = make_node(Color::Black, nullptr, nullptr, p);
    }
}

void PieceTable::insert(size_t offset, const std::string& text) {
    if (text.empty()) return;

    // Append to a new add buffer
    size_t buf_id = buffers_.size();
    buffers_.push_back(text);

    Piece p = { buf_id, 0, text.size() };
    root_ = rb_insert(root_, offset, p);
    current_snapshot_ = snapshot_counter_++;
}

void PieceTable::erase(size_t offset, size_t len) {
    if (len == 0) return;
    root_ = rb_erase(root_, offset, len);
    current_snapshot_ = snapshot_counter_++;
}

std::string PieceTable::text() const {
    return rb_text(root_, buffers_);
}

size_t PieceTable::length() const {
    return rb_size(root_);
}

size_t PieceTable::line_count() const {
    std::string t = text();
    if (t.empty()) return 0;
    size_t count = 1;
    for (char c : t) {
        if (c == '\n') count++;
    }
    // If last char is \n, don't add extra
    if (!t.empty() && t.back() == '\n') count--;
    return count;
}

std::string PieceTable::line_at(size_t line_index) const {
    std::string t = text();
    std::istringstream ss(t);
    std::string line;
    size_t idx = 0;
    while (std::getline(ss, line)) {
        if (idx == line_index) return line;
        idx++;
    }
    return "";
}

size_t PieceTable::snapshot_id() const {
    return current_snapshot_;
}

} // namespace fredbuf
