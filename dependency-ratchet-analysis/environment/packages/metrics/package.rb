# frozen_string_literal: true
# typed: strict

class Metrics < PackageSpec
  # Application metrics collection and reporting.
  # Supports StatsD, Prometheus, and custom backends.
  layer 'utility'
  strict_dependencies 'layered'

  import Config
  import Logging
end
