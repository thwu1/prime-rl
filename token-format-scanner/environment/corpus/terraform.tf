terraform {
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }
}

variable "github_token" {
  description = "GitHub token for Terraform provider authentication"
  default     = "ghs_tL1eX5zIvR3wYnSg8CfMqU0dHkB6gA2YpjB1"
  sensitive   = true
}

provider "github" {
  token = var.github_token
  owner = "acme-corp"
}

resource "github_repository" "main" {
  name        = "acme-service"
  description = "Primary application repository"
  visibility  = "private"

  has_issues   = true
  has_projects = false
  has_wiki     = false

  allow_merge_commit = false
  allow_squash_merge = true
  allow_rebase_merge = true

  delete_branch_on_merge = true
}

resource "github_branch_protection" "main" {
  repository_id = github_repository.main.node_id
  pattern       = "main"

  required_status_checks {
    strict = true
    contexts = ["ci/build", "ci/test"]
  }

  required_pull_request_reviews {
    required_approving_review_count = 1
  }
}
