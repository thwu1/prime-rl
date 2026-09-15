#!/usr/bin/awk -f
# Fixed normalizer: handles pipe-delimited, comma-separated, comments, duplicates
#

# Skip comment lines
/^[[:space:]]*#/ { next }

{
    delete seen
    delete items
    count = 0

    line = $0

    # Handle pipe-delimited format (e.g., TXN-001|5,2,8)
    if (index(line, "|") > 0) {
        n = split(line, pipe_parts, "|")
        if (n >= 2) {
            line = pipe_parts[2]
        }
    }

    # Determine separator and split tokens
    if (index(line, ",") > 0) {
        n = split(line, tokens, ",")
    } else {
        n = split(line, tokens, " ")
    }

    for (i = 1; i <= n; i++) {
        val = tokens[i]
        gsub(/^[ \t]+|[ \t]+$/, "", val)
        if (val ~ /^[0-9]+$/) {
            num = val + 0
            if (!(num in seen)) {
                seen[num] = 1
                count++
                items[count] = num
            }
        }
    }

    if (count > 0) {
        # Insertion sort for ascending order
        for (i = 2; i <= count; i++) {
            key = items[i]
            j = i - 1
            while (j >= 1 && items[j] > key) {
                items[j+1] = items[j]
                j--
            }
            items[j+1] = key
        }

        printf "%d", items[1]
        for (i = 2; i <= count; i++) {
            printf " %d", items[i]
        }
        printf "\n"
    }
}
