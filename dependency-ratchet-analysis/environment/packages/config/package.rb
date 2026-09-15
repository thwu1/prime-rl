# frozen_string_literal: true
# typed: strict

class Config < PackageSpec
  # Centralized configuration management.
  # Reads from environment, YAML files, and remote config store.
  layer 'utility'
  strict_dependencies 'layered_dag'
end
