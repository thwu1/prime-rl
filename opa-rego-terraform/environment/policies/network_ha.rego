package network_ha

default is_valid = false

# Validate VPC exists with DNS support enabled
has_vpc {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_vpc"
    resource.values.cidr_block
    resource.values.enable_dns_support == true
}

# Validate at least 2 subnets exist
has_minimum_subnets {
    subnets := [r | r := input.planned_values.root_module.resources[_]; r.type == "aws_subnet"]
    count(subnets) >= 2
}

# Validate subnets span multiple availability zones for high availability
has_az_diversity {
    resource1 := input.configuration.root_module.resources[_]
    resource1.type == "aws_subnet"
    az1 := resource1.values.availability_zone

    resource2 := input.configuration.root_module.resources[_]
    resource2.type == "aws_subnet"
    az2 := resource2.values.availability_zone

    az1 != az2
}

# Validate security group restricts ingress to HTTPS only
has_restricted_ingress {
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_security_group"
    ingress := resource.values.ingress[_]
    ingress.source_port == 443
    ingress.to_port == 443
    ingress.protocol == "tcp"
}

is_valid {
    has_vpc
    has_minimum_subnets
    has_az_diversity
    has_restricted_ingress
}
