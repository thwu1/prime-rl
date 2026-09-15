# frozen_string_literal: true
# typed: strict

class ApiTransactions < PackageSpec
  # REST API endpoints for transaction operations.
  layer 'api'
  strict_dependencies 'layered'

  import Transactions
  import Merchants
  import Logging
  import Config
  import Refunds
end
