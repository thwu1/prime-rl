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

module "network" {
  source      = "./modules/network"
  environment = var.environment
  subnets     = var.subnets
}

module "application" {
  source      = "./modules/application"
  environment = var.environment
  app_config  = var.app_config
}

module "monitoring" {
  source          = "./modules/monitoring"
  app_config      = var.app_config
  alert_endpoints = var.alert_endpoints
  service_health  = module.application.health_endpoints
}
