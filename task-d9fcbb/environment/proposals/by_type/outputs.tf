output "network_config_path" {
  value = module.file_resources.network_config_path
}

output "app_config_files" {
  value = module.file_resources.app_config_files
}

output "active_alerts" {
  value = module.runtime_resources.active_alerts
}
