# frozen_string_literal: true
# typed: strict

class Database < PackageSpec
  # Database connection pooling, query builder, and migration runner.
  layer 'utility'
  strict_dependencies 'layered'

  import Config
  import Logging
end
