package terraform.validation

default is_configuration_valid = false
default is_valid_role = false
default is_valid_policy = false
default is_valid_attachment = false
default is_valid_profile = false

is_valid_role {
    some i
    resource := input.resource_changes[i]
    resource.type == "aws_iam_role"
    resource.change.after.name == "app-role"
    contains(resource.change.after.assume_role_policy, "ec2.amazonaws.com")
}

is_valid_policy {
    some i
    resource := input.configuration.root_module.resources[i]
    resource.type == "aws_iam_policy"
    resource.expressions.name
    resource.expressions.policy
}

is_valid_attachment {
    some i
    resource := input.configuration.root_module.resources[i]
    resource.type == "aws_iam_role_policy_attachment"
    resource.expressions.role.references[_] == "aws_iam_role.app_role"
    resource.expressions.policy_arn.references[_] == "aws_iam_policy.app_policy"
}

is_valid_profile {
    some i
    resource := input.configuration.root_module.resources[i]
    resource.type == "aws_iam_instance_profile"
    resource.expressions.name.constant_value == "app-profile"
    resource.expressions.role.references[_] == "aws_iam_role.app_role"
}

is_configuration_valid {
    is_valid_role
    is_valid_policy
    is_valid_attachment
    is_valid_profile
}
