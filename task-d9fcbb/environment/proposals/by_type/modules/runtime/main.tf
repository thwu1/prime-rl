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

variable "alert_endpoints" {
  type = map(object({
    url      = string
    severity = string
    active   = bool
  }))
}

resource "null_resource" "health_check" {
  for_each = { for k, v in var.app_config : k => v if v.enabled }
  triggers = {
    port = each.value.port
    app  = each.key
  }
}

resource "terraform_data" "deployment_metadata" {
  input = {
    deployed_at = "2024-01-15T10:00:00Z"
    version     = "1.0.0"
    environment = var.environment
  }
}

resource "null_resource" "alert_notifier" {
  for_each = { for k, v in var.alert_endpoints : k => v if v.active }
  triggers = {
    url      = each.value.url
    severity = each.value.severity
    channel  = each.key
  }
}

output "active_alerts" {
  value = { for k, v in null_resource.alert_notifier : k => v.triggers["channel"] }
}
