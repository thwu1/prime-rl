package terraform.validation

default is_configuration_valid = false
default is_valid_vpc = false
default is_valid_subnet_public = false
default is_valid_subnet_private = false
default is_valid_security_group = false

is_valid_vpc {
    some i
    resource := input.configuration.root_module.resources[i]
    resource.type == "aws_vpc"
    resource.expressions.cidr_block.constant_value == "10.0.0.0/16"
    resource.expressions.enable_dns_hostnames.constant_value == true
    resource.expressions.enable_dns_support.constant_value == true
}

is_valid_subnet_public {
    some i
    resource := input.configuration.root_module.resources[i]
    resource.type == "aws_subnet"
    resource.name == "public"
    resource.expressions.cidr_block.constant_value == "10.0.1.0/24"
    resource.expressions.vpc_id.references[_] == "aws_vpc.main"
}

is_valid_subnet_private {
    some i
    resource := input.configuration.root_module.resources[i]
    resource.type == "aws_subnet"
    resource.name == "private"
    resource.expressions.cidr_block.constant_value == "10.0.2.0/24"
    resource.expressions.vpc_id.references[_] == "aws_vpc.main"
}

is_valid_security_group {
    some i, j
    resource := input.resource_changes[i]
    resource.type == "aws_security_group"
    resource.change.after.name == "web-sg"
    ingress_rule := resource.change.after.ingress[j]
    ingress_rule.from_port == 443
    ingress_rule.to_port == 443
    ingress_rule.protocol == "tcp"
}

is_configuration_valid {
    is_valid_vpc
    is_valid_subnet_public
    is_valid_subnet_private
    is_valid_security_group
}
