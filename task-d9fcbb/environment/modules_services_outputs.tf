output "config_files" {
  value = { for k, v in local_file.app_configs : k => v.filename }
}

output "health_endpoints" {
  value = { for k, v in null_resource.health_check : k => v.triggers["port"] }
}
