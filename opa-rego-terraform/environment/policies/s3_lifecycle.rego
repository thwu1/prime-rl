package s3_lifecycle

default is_valid = false

has_s3_bucket {
    input.planned_values.root_module.resources[_].type == "aws_s3_bucket"
}

bucket_missing_lifecycle {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_s3_bucket"
    not has_valid_lifecycle(resource)
}

has_valid_lifecycle(res) {
    rule := res.values.lifecycle_rule[_]
    rule.enabled == true
    rule.expiration.days > 0
}

is_valid {
    has_s3_bucket
    not bucket_missing_lifecycle
}
