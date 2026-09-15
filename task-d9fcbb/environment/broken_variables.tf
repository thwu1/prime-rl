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
