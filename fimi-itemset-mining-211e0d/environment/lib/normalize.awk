#!/usr/bin/awk -f
# Normalize transaction data to standard FIMI format
# Input: various formats (space/comma/pipe separated)
# Output: one transaction per line, space-separated sorted unique integers
#

{
    delete items
    count = 0

    # Parse tokens from line using space separator
    n = split($0, tokens, " ")

    for (i = 1; i <= n; i++) {
        val = tokens[i]
        gsub(/^[ \t]+|[ \t]+$/, "", val)
        if (val ~ /^[0-9]+$/) {
            count++
            items[count] = val + 0
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

        # Output sorted items
        printf "%d", items[1]
        for (i = 2; i <= count; i++) {
            printf " %d", items[i]
        }
        printf "\n"
    }
}
