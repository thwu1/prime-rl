package iam_least_privilege

default is_valid = false

has_iam_policy {
    input.planned_values.root_module.resources[_].type == "aws_iam_policy"
}

wildcard_violation {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_iam_policy"
    policy := json.unmarshal(resource.values.policy_document)
    statement := policy.Statement[_]
    statement.Action == "*"
    statement.Resource == "*"
}

is_valid {
    has_iam_policy
    not wildcard_violation
}
