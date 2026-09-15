variable "app_config" {
  type = map(object({
    port     = number
    replicas = number
    enabled  = bool
  }))
}

variable "environment" {
  type = string
}

variable "enabled_services" {
  type    = list(string)
  default = ["api", "worker"]
}
