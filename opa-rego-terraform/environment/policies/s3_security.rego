package s3_security

default is_valid = false

# Validate S3 bucket has versioning enabled
has_versioning {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_s3_bucket"
    resource.values.versioning.enabled == true
}

# Validate S3 bucket has KMS server-side encryption
has_encryption {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_s3_bucket"
    resource.values.server_side_encryption_configuration.rule.apply_server_side_encryption_by_default.sse_algorithm == "aws:kms"
}

# Validate public access is blocked
has_public_access_block {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_s3_bucket_public_access_block_config"
    resource.values.block_public_acls == true
    resource.values.block_public_policy == true
    resource.values.ignore_public_acls == true
    resource.values.restrict_public_buckets == true
}

is_valid {
    has_versioning
    has_encryption
    has_public_access_block
}
