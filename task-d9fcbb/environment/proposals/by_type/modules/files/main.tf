variable "environment" {
  type = string
}

variable "app_config" {
  type = map(object({
    port     = number
    replicas = number
    enabled  = bool
  }))
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

resource "local_file" "app_configs" {
  for_each = var.app_config
  filename = "/app/generated/app/${each.key}.json"
  content  = jsonencode({
    name     = each.key
    port     = each.value.port
    replicas = each.value.replicas
    env      = var.environment
  })
}

resource "local_file" "deployment_manifest" {
  filename = "/app/generated/manifest.yaml"
  content  = yamlencode({
    apiVersion = "v1"
    kind       = "DeploymentManifest"
    metadata   = { name = "app-deployment", environment = var.environment }
    spec = {
      services = { for k, v in var.app_config : k => {
        port     = v.port
        replicas = v.replicas
        status   = v.enabled ? "active" : "disabled"
      }}
    }
  })
}

resource "local_file" "alert_rules" {
  filename = "/app/generated/monitoring/alerts.yaml"
  content  = yamlencode({
    rules = [for k, v in var.app_config : {
      name    = "${k}-health"
      port    = v.port
      enabled = v.enabled
    }]
  })
}

output "network_config_path" {
  value = local_file.network_config.filename
}

output "app_config_files" {
  value = { for k, v in local_file.app_configs : k => v.filename }
}
