# preprocess.awk — Filter PLUMED HILLS file by time window.
# Invocation: gawk -v tmin=<float> -v tmax=<float> -f preprocess.awk <hills_file>
#

/^#!/ { print; next }
/^#/  { next }
/^[[:space:]]*$/ { next }
{
    t = $1 + 0
    if (t >= tmin && t <= tmax) print
}
