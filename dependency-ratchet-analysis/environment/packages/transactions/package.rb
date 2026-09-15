# frozen_string_literal: true
# typed: strict

class Transactions < PackageSpec
  # Payment transaction lifecycle: authorization, capture,
  # settlement, and reconciliation.
  layer 'business'
  strict_dependencies 'layered'

  import Database
  import Logging
  import Config
  import PaymentGateway
  import Merchants
  import Customers
end
