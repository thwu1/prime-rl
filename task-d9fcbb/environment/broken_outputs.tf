output "config_files" {
  value = module.services.config_files
}

output "enabled_apps" {
  value = [for k, v in var.app_config : k if v.enabled]
}
