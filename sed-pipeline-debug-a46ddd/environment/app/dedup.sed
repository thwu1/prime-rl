# Remove consecutive duplicate lines (like uniq)
$!N
/^\(.*\)\n\1/!P
d
