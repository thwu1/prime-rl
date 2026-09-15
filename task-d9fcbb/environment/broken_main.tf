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

module "services" {
  source = "./modules/services"

  app_config  = var.app_config
  environment = var.environment
}

resource "local_file" "main_config" {
  filename = "/app/generated/main.json"
  content  = jsonencode({
    apps        = [for k, v in var.app_config : k if v.enabled]
    environment = var.environment
  })
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
    metadata = {
      name        = "app-deployment"
      environment = var.environment
    }
    spec = {
      services = { for k, v in var.app_config : k => {
        port     = v.port
        replicas = v.replicas
        status   = v.enabled ? "active" : "disabled"
      }}
    }
  })
}
