rule score_fabrication_pattern
{
    meta:
        description = "Detects score calibration or fabrication patterns in Python scripts"
        violation_type = "score_fabrication"

    strings:
        $cal = "calibrat" ascii nocase
        $adj = "adjusted_accuracy" ascii nocase
        $off = "calibration_offset" ascii nocase
        $target = "target_accuracy" ascii nocase
        $metrics_ref = /metrics.*\.json/ ascii
        $json_write = "json.dump" ascii

    condition:
        ($metrics_ref or $json_write) and any of ($cal, $adj, $off, $target)
}
