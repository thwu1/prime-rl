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

module "file_resources" {
  source      = "./modules/files"
  environment = var.environment
  app_config  = var.app_config
  subnets     = var.subnets
}

module "runtime_resources" {
  source          = "./modules/runtime"
  environment     = var.environment
  app_config      = var.app_config
  alert_endpoints = var.alert_endpoints
}

moved {
  from = local_file.network_config
  to   = module.file_resources.local_file.network_config
}

moved {
  from = local_file.subnet_configs
  to   = module.file_resources.local_file.subnet_configs
}

moved {
  from = local_file.app_configs
  to   = module.file_resources.local_file.app_configs
}

moved {
  from = local_file.deployment_manifest
  to   = module.file_resources.local_file.deployment_manifest
}

moved {
  from = local_file.alert_rules
  to   = module.file_resources.local_file.alert_rules
}

moved {
  from = null_resource.health_check
  to   = module.runtime_resources.null_resource.health_check
}

moved {
  from = null_resource.alert_notifier
  to   = module.runtime_resources.null_resource.alert_notifier
}

moved {
  from = terraform_data.deployment_metadata
  to   = module.runtime_resources.terraform_data.deployment_metadata
}
