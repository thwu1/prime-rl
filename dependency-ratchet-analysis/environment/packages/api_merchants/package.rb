# frozen_string_literal: true
# typed: strict

class ApiMerchants < PackageSpec
  # REST API endpoints for merchant management.
  layer 'api'
  strict_dependencies 'layered'

  import Merchants
  import Customers
  import Logging
  import Config
end
