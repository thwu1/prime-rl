resource "local_file" "app_configs" {
  for_each = var.app_config
  filename = "/app/generated/configs/${each.key}.json"
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
    service = each.value
  }
}
