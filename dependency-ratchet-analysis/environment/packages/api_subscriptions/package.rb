# frozen_string_literal: true
# typed: strict

class ApiSubscriptions < PackageSpec
  # REST API endpoints for subscription and invoice management.
  layer 'api'
  strict_dependencies 'false'

  import Subscriptions
  import Invoices
  import Transactions
  import Logging
  import Config
end
