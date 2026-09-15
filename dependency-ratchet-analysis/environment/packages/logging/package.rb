# frozen_string_literal: true
# typed: strict

class Logging < PackageSpec
  # Core structured logging infrastructure.
  # Supports pluggable formatters and output sinks.
  layer 'utility'
  strict_dependencies 'layered'

  import Config
  import Merchants  # merchant PII redaction support
end
