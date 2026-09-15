# frozen_string_literal: true
# typed: strict

class Invoices < PackageSpec
  # Invoice generation, line items, tax calculation,
  # and PDF rendering.
  layer 'business'
  strict_dependencies 'layered'

  import Database
  import Logging
  import Config
  import Transactions
  import Merchants
  import Subscriptions
end
