package terraform.validation

default is_configuration_valid = false
default is_valid_zone = false
default is_valid_elb = false
default is_valid_record = false

is_valid_zone {
    some i
    resource := input.configuration.root_module.resources[i]
    resource.type == "aws_route53_zone"
    resource.expressions.name.constant_value == "example.com"
}

is_valid_elb {
    some i
    resource := input.configuration.root_module.resources[i]
    resource.type == "aws_elb"
    resource.expressions.name
    listener := resource.expressions.listener[0]
    listener.lb_port
    listener.instance_port
}

is_valid_record {
    some i
    resource := input.resource_changes[i]
    resource.type == "aws_route53_record"
    resource.change.after.type == "A"

    some j
    config := input.configuration.root_module.resources[j]
    config.type == "aws_route53_record"
    config.expressions.zone_id.references[_] == "aws_route53_zone.primary"
}

is_configuration_valid {
    is_valid_zone
    is_valid_elb
    is_valid_record
}
