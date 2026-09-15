
#include <fredbuf/undo_tree.h>
#include <stdexcept>

namespace fredbuf {

UndoTree::UndoTree() : next_id_(1) {
    // Create root history node (empty state)
    HistoryNode root_node;
    root_node.id = 0;
    root_node.root = nullptr;
    root_node.parent_id = 0;
    nodes_[0] = root_node;
    current_node_id_ = 0;
}

void UndoTree::insert(size_t offset, const std::string& text) {
    pt_.insert(offset, text);
}

void UndoTree::erase(size_t offset, size_t length) {
    pt_.erase(offset, length);
}

std::string UndoTree::text() const {
    return pt_.text();
}

void UndoTree::commit() {
    HistoryNode new_node;
    new_node.id = next_id_++;
    new_node.root = pt_.root();
    new_node.parent_id = current_node_id_;

    nodes_[new_node.id] = new_node;
    nodes_[current_node_id_].children.push_back(new_node.id);
    current_node_id_ = new_node.id;
}

void UndoTree::undo() {
    auto it = nodes_.find(current_node_id_);
    if (it == nodes_.end()) return;
    if (current_node_id_ == 0) return; // already at root

    size_t parent_id = it->second.parent_id;
    auto pit = nodes_.find(parent_id);
    if (pit == nodes_.end()) return;

    current_node_id_ = parent_id;
    pt_.set_root(pit->second.root);
}

void UndoTree::redo(size_t branch_index) {
    auto it = nodes_.find(current_node_id_);
    if (it == nodes_.end()) return;
    if (branch_index >= it->second.children.size()) return;

    size_t child_id = it->second.children[branch_index];
    auto cit = nodes_.find(child_id);
    if (cit == nodes_.end()) return;

    current_node_id_ = child_id;
    pt_.set_root(cit->second.root);
}

size_t UndoTree::history_node_count() const {
    return nodes_.size();
}

size_t UndoTree::branches_at(size_t snapshot_id) const {
    auto it = nodes_.find(snapshot_id);
    if (it == nodes_.end()) return 0;
    return it->second.children.size();
}

void UndoTree::checkout(size_t snapshot_id) {
    auto it = nodes_.find(snapshot_id);
    if (it == nodes_.end()) {
        throw std::runtime_error("Invalid snapshot ID");
    }
    current_node_id_ = snapshot_id;
    pt_.set_root(it->second.root);
}

std::string UndoTree::text_at(size_t snapshot_id) const {
    auto it = nodes_.find(snapshot_id);
    if (it == nodes_.end()) {
        throw std::runtime_error("Invalid snapshot ID");
    }
    return rb_text(it->second.root, pt_.buffers());
}

size_t UndoTree::current_snapshot_id() const {
    return current_node_id_;
}

} // namespace fredbuf
