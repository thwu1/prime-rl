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

variable "service_health" {
  type = list(string)
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

resource "null_resource" "alert_notifier" {
  for_each = tolist(var.alert_endpoints)

  triggers = {
    endpoint = each.value.url
    severity = each.value.severity
    channel  = each.key
  }
}

output "active_alerts" {
  value = { for k, v in null_resource.alert_notifier : k => v.triggers["channel"] }
}
