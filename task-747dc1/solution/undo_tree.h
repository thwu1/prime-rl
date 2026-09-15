#pragma once

#include <fredbuf/piece_table.h>
#include <string>
#include <vector>
#include <unordered_map>
#include <memory>

namespace fredbuf {

struct HistoryNode {
    size_t id;
    RBNodePtr root;             // piece table root at this snapshot
    size_t parent_id;           // 0 if root node
    std::vector<size_t> children;
};

class UndoTree {
public:
    UndoTree();

    // Piece table operations (delegated)
    void insert(size_t offset, const std::string& text);
    void erase(size_t offset, size_t length);
    std::string text() const;

    // Undo tree operations
    void commit();
    void undo();
    void redo(size_t branch_index);

    size_t history_node_count() const;
    size_t branches_at(size_t snapshot_id) const;
    void checkout(size_t snapshot_id);
    std::string text_at(size_t snapshot_id) const;
    size_t current_snapshot_id() const;

private:
    PieceTable pt_;
    std::unordered_map<size_t, HistoryNode> nodes_;
    size_t current_node_id_;
    size_t next_id_;
};

} // namespace fredbuf
