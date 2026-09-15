variable "environment" {
  type    = string
  default = "production"

  validation {
    condition     = contains(["production", "staging", "development"], var.environment)
    error_message = "Must be production, staging, or development."
  }
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
