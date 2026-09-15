# frozen_string_literal: true
# typed: strict

class HttpClient < PackageSpec
  # HTTP client wrapper with retry logic, circuit breaking,
  # and request/response logging.
  layer 'utility'
  strict_dependencies 'false'

  import Logging
  import Config
end
