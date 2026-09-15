variable "environment" {
  type = string
}

variable "subnets" {
  type = map(object({
    cidr   = string
    public = bool
  }))
}

resource "local_file" "network_config" {
  filename = "/app/generated/network/config.json"
  content  = jsonencode({
    environment = var.environment
    subnets     = var.subnets
  })
}

resource "local_file" "subnet_configs" {
  for_each = var.subnets
  filename = "/app/generated/network/${each.key}.json"
  content  = jsonencode({
    name   = each.key
    cidr   = each.value.cidr
    public = each.value.public
  })
}
