# frozen_string_literal: true
# typed: strict

class CronService < PackageSpec
  # Scheduled job runner for periodic tasks:
  # invoice finalization, subscription renewals, cleanup.
  layer 'services'
  strict_dependencies 'false'

  import Transactions
  import Invoices
  import Subscriptions
  import Logging
  import Config
  import Database
end
