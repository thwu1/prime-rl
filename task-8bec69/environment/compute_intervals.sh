#!/bin/bash
# Compute interval deltas from JSON metric snapshots using jq
# Reads paired JSON snapshots and produces interval delta files

set -e

INPUT_DIR="/app/json_snapshots"
OUTPUT_DIR="/app/intervals"
mkdir -p "$OUTPUT_DIR"

# Get sorted timestamps
timestamps=($(ls "$INPUT_DIR"/*.json 2>/dev/null | xargs -I{} basename {} .json | sort -n))

if [ ${#timestamps[@]} -lt 2 ]; then
    echo "Error: need at least 2 snapshots" >&2
    exit 1
fi

for ((i=0; i<${#timestamps[@]}-1; i++)); do
    ts_old=${timestamps[$i]}
    ts_new=${timestamps[$((i+1))]}

    jq -n \
        --slurpfile old "$INPUT_DIR/${ts_old}.json" \
        --slurpfile new_ "$INPUT_DIR/${ts_new}.json" \
        '
        $old[0] as $o | $new_[0] as $n |

        # Counter deltas with reset detection
        (
            $n.counters | to_entries | map(
                .key as $k | .value as $nv |
                ($o.counters[$k] // 0) as $ov |
                if $nv < $ov then
                    {key: $k, value: $nv, reset: true}
                else
                    {key: $k, value: ($nv - $ov), reset: false}
                end
            )
        ) as $counter_entries |

        ($counter_entries | any(.reset)) as $counter_reset |

        # Histogram deltas
        (
            $n.histograms | to_entries | map(
                .key as $metric |
                .value as $nh |
                ($o.histograms[$metric] // {buckets:[], sum:0, count:0}) as $oh |

                # Check histogram bucket reset (any new count < old count)
                (
                    if ($oh.buckets | length) == 0 then false
                    else
                        [range($nh.buckets | length)] |
                        any(. as $idx |
                            $nh.buckets[$idx].cumulative_count < $oh.buckets[$idx].cumulative_count
                        )
                    end
                ) as $h_reset |

                {
                    key: $metric,
                    value: {
                        delta_buckets: (
                            if $h_reset then
                                [$nh.buckets[] | {upper_bound: .upper_bound, delta: .cumulative_count}]
                            else
                                $nh.buckets | [.[] | {upper_bound: .upper_bound, delta: .cumulative_count}]
                            end
                        ),
                        request_count_delta: (
                            if $h_reset then $nh.sum
                            else ($nh.sum - ($oh.sum // 0))
                            end
                        ),
                        reset_detected: $h_reset
                    }
                }
            ) | from_entries
        ) as $hist_deltas |

        ($counter_reset or ($hist_deltas | to_entries | any(.value.reset_detected))) as $any_reset |

        {
            start_ts: $o.timestamp,
            end_ts: $n.timestamp,
            duration_sec: ($n.timestamp - $o.timestamp),
            counter_reset_detected: $any_reset,
            counter_deltas: ($counter_entries | map({key: .key, value: .value}) | from_entries),
            histogram_deltas: $hist_deltas
        }
        ' > "$OUTPUT_DIR/interval_${i}.json"

    echo "Computed interval $i: $ts_old -> $ts_new"
done

echo "Done: $(ls "$OUTPUT_DIR"/interval_*.json 2>/dev/null | wc -l) intervals"
