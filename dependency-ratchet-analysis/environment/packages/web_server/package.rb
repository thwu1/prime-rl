# frozen_string_literal: true
# typed: strict

class WebServer < PackageSpec
  # Main web application server assembly.
  # Wires up API routes, middleware, and monitoring.
  layer 'services'
  strict_dependencies 'false'

  import ApiMerchants
  import ApiTransactions
  import ApiSubscriptions
  import ApiWebhooks
  import Logging
  import Config
  import HttpClient
end
