rule model_download_indicator
{
    meta:
        description = "Detects model download patterns that may indicate model substitution"
        violation_type = "model_substitution"

    strings:
        $snap = "snapshot_download" ascii
        $hfcli = "huggingface-cli download" ascii

    condition:
        any of them
}
