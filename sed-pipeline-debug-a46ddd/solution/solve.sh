#!/bin/bash
#
# Reference solution: fix all bugs across 4 files and implement fold.sed.

##############################################################################
# Fix 1: transform.sh
#   Bug A: missing -n flag on the number.sed invocation (auto-print leaks
#          counter values into output)
#   Bug B: pipeline order is wrong — fold runs before dedup, but the correct
#          order is join → dedup → fold → number (dedup must precede fold so
#          that duplicate tagged lines are collapsed before folding)
##############################################################################
cat > /app/transform.sh << 'SCRIPT'
#!/bin/bash
sed -f /app/join.sed "$@" | sed -f /app/dedup.sed | sed -f /app/fold.sed | sed -nf /app/number.sed
SCRIPT
chmod +x /app/transform.sh

##############################################################################
# Fix 2: join.sed — three bugs:
#   (a) N instead of $!N — loses last line when N fails at EOF
#   (b) p instead of P — prints entire multi-line buffer, not just first line
#   (c) d instead of D — discards entire buffer instead of sliding window
##############################################################################
cat > /app/join.sed << 'SEDSCRIPT'
# Join continuation lines (lines starting with "> " are appended to previous line)
:join
$!N
s/\n> / /
t join
P
D
SEDSCRIPT

##############################################################################
# Fix 3: dedup.sed — two bugs:
#   (a) Missing $ anchor after \1 — prefix matches falsely trigger dedup
#   (b) d instead of D — discards both lines instead of sliding window
##############################################################################
cat > /app/dedup.sed << 'SEDSCRIPT'
# Remove consecutive duplicate lines (like uniq)
$!N
/^\(.*\)\n\1$/!P
D
SEDSCRIPT

##############################################################################
# Fix 4: fold.sed — was an unimplemented stub. Full implementation:
#   - Lines without a colon pass through unchanged.
#   - For lines with a colon, extract the tag (text before first colon).
#   - Read the next line; if it shares the same tag, join the value portions
#     with " | " and loop to accumulate more.
#   - When the tag changes (or input ends), print the accumulated line and
#     continue with the non-matching line.
##############################################################################
cat > /app/fold.sed << 'SEDSCRIPT'
# Fold consecutive entries sharing a tag prefix (text before first colon).
/:/!{p;d}
:next
$!N
s/^\([^:]*\):\(.*\)\n\1: *\(.*\)$/\1:\2 | \3/
t next
P
D
SEDSCRIPT

##############################################################################
# Fix 5: number.sed — three bugs:
#   (a) Counter initialized to 000 instead of 001 — off-by-one start
#   (b) Missing s/0\(_*\)$/1\1/; tn — counter cannot increment from 0,
#       causing carry propagation to fail at 009→010, 019→020, etc.
#   (c) Swapped backreferences in format substitution: [\1] \2 produces
#       [line] counter instead of [counter] line — must be [\2] \1
##############################################################################
cat > /app/number.sed << 'SEDSCRIPT'
# Number each line with [NNN] prefix using arithmetic in sed

# Initialize counter on first line
1{
    x
    s/^$/001/
    x
}

# Format and print: [counter] line
G
s/\(.*\)\n\(.*\)/[\2] \1/p

# Increment counter
g
:d
s/9\(_*\)$/_\1/
td
s/^\(_*\)$/1\1/; tn
s/8\(_*\)$/9\1/; tn
s/7\(_*\)$/8\1/; tn
s/6\(_*\)$/7\1/; tn
s/5\(_*\)$/6\1/; tn
s/4\(_*\)$/5\1/; tn
s/3\(_*\)$/4\1/; tn
s/2\(_*\)$/3\1/; tn
s/1\(_*\)$/2\1/; tn
s/0\(_*\)$/1\1/; tn
:n
y/_/0/
h
SEDSCRIPT
