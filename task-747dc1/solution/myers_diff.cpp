
#include <fredbuf/myers_diff.h>
#include <sstream>
#include <algorithm>
#include <unordered_map>

namespace fredbuf {

static std::vector<std::string> split_lines(const std::string& text) {
    std::vector<std::string> lines;
    if (text.empty()) return lines;

    size_t start = 0;
    while (start < text.size()) {
        size_t end = text.find('\n', start);
        if (end == std::string::npos) {
            lines.push_back(text.substr(start));
            break;
        } else {
            lines.push_back(text.substr(start, end - start));
            start = end + 1;
        }
    }
    return lines;
}

std::vector<DiffHunk> myers_diff(const std::string& old_text, const std::string& new_text) {
    auto old_lines = split_lines(old_text);
    auto new_lines = split_lines(new_text);

    int N = static_cast<int>(old_lines.size());
    int M = static_cast<int>(new_lines.size());
    int MAX = N + M;

    if (MAX == 0) return {};

    // V array indexed from -MAX to MAX
    // Using offset to handle negative indices
    std::vector<std::vector<int>> trace;
    std::vector<int> v(2 * MAX + 1, 0);
    int offset = MAX;

    v[offset + 1] = 0;

    bool found = false;
    for (int d = 0; d <= MAX; d++) {
        trace.push_back(v);
        for (int k = -d; k <= d; k += 2) {
            int x;
            if (k == -d || (k != d && v[offset + k - 1] < v[offset + k + 1])) {
                x = v[offset + k + 1];
            } else {
                x = v[offset + k - 1] + 1;
            }
            int y = x - k;

            while (x < N && y < M && old_lines[x] == new_lines[y]) {
                x++;
                y++;
            }

            v[offset + k] = x;

            if (x >= N && y >= M) {
                found = true;
                break;
            }
        }
        if (found) break;
    }

    // Backtrack to find the edit script
    struct Edit {
        int prev_x, prev_y, x, y;
    };

    std::vector<Edit> edits;
    int x = N, y = M;

    for (int d = static_cast<int>(trace.size()) - 1; d >= 0; d--) {
        auto& vd = trace[d];
        int k = x - y;

        int prev_k;
        if (k == -d || (k != d && vd[offset + k - 1] < vd[offset + k + 1])) {
            prev_k = k + 1;
        } else {
            prev_k = k - 1;
        }

        int prev_x = vd[offset + prev_k];
        int prev_y = prev_x - prev_k;

        // Diagonal moves (equal lines)
        while (x > prev_x && y > prev_y) {
            x--;
            y--;
            edits.push_back({x, y, x + 1, y + 1});
        }

        if (d > 0) {
            if (x == prev_x) {
                // Insertion
                y--;
                edits.push_back({prev_x, y, prev_x, y + 1});
            } else {
                // Deletion
                x--;
                edits.push_back({x, prev_y, x + 1, prev_y});
            }
        }

        x = prev_x;
        y = prev_y;
    }

    std::reverse(edits.begin(), edits.end());

    // Convert edits to DiffHunks
    std::vector<DiffHunk> hunks;
    for (auto& e : edits) {
        if (e.x - e.prev_x == 1 && e.y - e.prev_y == 1) {
            // Equal
            DiffHunk h;
            h.op = DiffHunk::Equal;
            h.line = old_lines[e.prev_x];
            h.old_lineno = e.prev_x;
            h.new_lineno = e.prev_y;
            hunks.push_back(h);
        } else if (e.x - e.prev_x == 1 && e.y == e.prev_y) {
            // Delete
            DiffHunk h;
            h.op = DiffHunk::Delete;
            h.line = old_lines[e.prev_x];
            h.old_lineno = e.prev_x;
            h.new_lineno = -1;
            hunks.push_back(h);
        } else if (e.x == e.prev_x && e.y - e.prev_y == 1) {
            // Insert
            DiffHunk h;
            h.op = DiffHunk::Insert;
            h.line = new_lines[e.prev_y];
            h.old_lineno = -1;
            h.new_lineno = e.prev_y;
            hunks.push_back(h);
        }
    }

    return hunks;
}

} // namespace fredbuf
