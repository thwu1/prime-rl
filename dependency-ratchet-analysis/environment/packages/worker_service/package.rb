# frozen_string_literal: true
# typed: strict

class WorkerService < PackageSpec
  # Background job processing service.
  # Handles async tasks: emails, settlement, reconciliation.
  layer 'services'
  strict_dependencies 'false'

  import Transactions
  import Subscriptions
  import Invoices
  import Refunds
  import Logging
  import Config
  import EmailProvider
  import SmsProvider
end
