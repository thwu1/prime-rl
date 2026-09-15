rule gpqa_dataset_reference
{
    meta:
        description = "References to GPQA benchmark dataset in training or data code"
        violation_type = "data_contamination"

    strings:
        $ds_name = "Idavidrein/gpqa" ascii
        $ds_subset = "gpqa_main" ascii
        $ds_diamond = "gpqa_diamond" ascii

    condition:
        any of them
}
