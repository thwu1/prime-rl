# frozen_string_literal: true
# typed: strict

class Subscriptions < PackageSpec
  # Recurring billing: plans, subscription lifecycle,
  # proration, and dunning.
  layer 'business'
  strict_dependencies 'layered_dag'

  import Database
  import Logging
  import Config
  import PaymentGateway
  import Transactions
  import Invoices
end
