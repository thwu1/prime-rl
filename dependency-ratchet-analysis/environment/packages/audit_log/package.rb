# frozen_string_literal: true
# typed: strict

class AuditLog < PackageSpec
  # Immutable audit trail for compliance-sensitive operations.
  # Captures actor, action, resource, and diff.
  layer 'business'
  strict_dependencies 'layered'

  import Database
  import Logging
  import Config
  import Merchants
  import Transactions
end
