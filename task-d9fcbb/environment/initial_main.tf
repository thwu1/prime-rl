terraform {
  required_providers {
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

variable "environment" {
  type    = string
  default = "production"
}

variable "app_config" {
  type = map(object({
    port     = number
    replicas = number
    enabled  = bool
  }))
  default = {
    api = {
      port     = 8080
      replicas = 3
      enabled  = true
    }
    worker = {
      port     = 9090
      replicas = 2
      enabled  = true
    }
    scheduler = {
      port     = 7070
      replicas = 1
      enabled  = false
    }
  }
}

variable "subnets" {
  type = map(object({
    cidr   = string
    public = bool
  }))
  default = {
    public  = { cidr = "10.0.1.0/24", public = true }
    private = { cidr = "10.0.2.0/24", public = false }
  }
}

variable "alert_endpoints" {
  type = map(object({
    url      = string
    severity = string
    active   = bool
  }))
  default = {
    pagerduty = { url = "https://events.pagerduty.com", severity = "critical", active = true }
    slack     = { url = "https://hooks.slack.com/T00",   severity = "warning",  active = true }
  }
}

# --- Networking ---
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

# --- Application ---
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

# --- Monitoring ---
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
  for_each = { for k, v in var.alert_endpoints : k => v if v.active }
  triggers = {
    url      = each.value.url
    severity = each.value.severity
    channel  = each.key
  }
}

# --- Outputs ---
output "network_config_path" {
  value = local_file.network_config.filename
}

output "app_config_files" {
  value = { for k, v in local_file.app_configs : k => v.filename }
}

output "active_alerts" {
  value = { for k, v in null_resource.alert_notifier : k => v.triggers["channel"] }
}
