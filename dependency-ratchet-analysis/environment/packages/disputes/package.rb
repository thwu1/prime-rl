# frozen_string_literal: true
# typed: strict

class Disputes < PackageSpec
  # Chargeback and dispute management: evidence collection,
  # response deadlines, and resolution tracking.
  layer 'business'
  strict_dependencies 'false'

  import Database
  import Logging
  import Config
  import Transactions
  import Merchants
  import Refunds
  import Customers
  import ApiWebhooks  # webhook notifications for dispute updates
end
