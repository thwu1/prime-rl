package iam_trust

default is_valid = false

# Validate IAM role with proper assume role policy for Lambda service
is_valid_role {
    resource := input.resource_changes[_]
    resource.type == "aws_iam_policy"
    policy_str := resource.change.after.trust_policy
    policy := json.unmarshal(policy_str)
    statement := policy.Statement[_]
    statement.Principal.Service == "lambda.amazonaws.com"
    statement.Action == "sts:AssumeRole"
}

# Validate policy attachment exists linking role to policy
has_policy_attachment {
    resource := input.resource_changes[_]
    resource.type == "aws_iam_role_policy_attachment"
    resource.change.after.role
    resource.change.after.policy_arn
}

is_valid {
    is_valid_role
    has_policy_attachment
}
