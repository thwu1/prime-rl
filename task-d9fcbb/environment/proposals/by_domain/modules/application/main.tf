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

# NOTE: this variable is incorrectly defined and used
variable "enabled_services" {
  type    = list(string)
  default = []
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

resource "null_resource" "health_check" {
  for_each = var.enabled_services

  triggers = {
    service_port = each.value
    app_name     = each.key
  }
}

resource "terraform_data" "deployment_metadata" {
  input = {
    deployed_at = "2024-01-15T10:00:00Z"
    version     = "1.0.0"
    environment = var.environment
  }
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

output "app_config_files" {
  value = { for k, v in local_file.app_configs : k => v.filename }
}

output "health_endpoints" {
  value = { for k, v in null_resource.health_check : k => v.triggers["port_number"] }
}
