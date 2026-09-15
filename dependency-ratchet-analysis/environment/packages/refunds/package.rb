# frozen_string_literal: true
# typed: strict

class Refunds < PackageSpec
  # Refund processing: full and partial refunds,
  # balance adjustments, and reversal handling.
  layer 'business'
  strict_dependencies 'dag'

  import Database
  import Logging
  import Config
  import Transactions
  import PaymentGateway
end
