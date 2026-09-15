terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket = "terraform-state-platform"
    key    = "prod/infrastructure.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  default = "us-east-1"
}

variable "environment" {
  default = "production"
}

# Beacon analytics token for server-side event tracking
resource "aws_ssm_parameter" "beacon_token" {
  name        = "/platform/${var.environment}/beacon_token"
  description = "Beacon Analytics API token"
  type        = "SecureString"
  value       = "bcn-162f803d7caf9fe9b8d8eb743ac8a41445823bb1-674d0a12"

  tags = {
    Environment = var.environment
    ManagedBy   = "terraform"
    Service     = "analytics"
  }
}

# Old delta key that was used during testing - should be removed
resource "aws_ssm_parameter" "delta_test_key" {
  name        = "/platform/${var.environment}/delta_test_sk"
  description = "Delta test secret key (DEPRECATED)"
  type        = "SecureString"
  value       = "dlt_sk_Eu8SFF0ntg9RLadQFqCNTEZZzIye"

  tags = {
    Environment = var.environment
    ManagedBy   = "terraform"
    Deprecated  = "true"
  }
}

resource "aws_security_group" "api" {
  name_prefix = "platform-api-"
  vpc_id      = data.aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "platform-api-sg"
  }
}

data "aws_vpc" "main" {
  default = true
}
