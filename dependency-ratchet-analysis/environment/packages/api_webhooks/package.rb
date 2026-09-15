# frozen_string_literal: true
# typed: strict

class ApiWebhooks < PackageSpec
  # Outbound webhook delivery and retry infrastructure.
  layer 'api'
  strict_dependencies 'layered'

  import Merchants
  import Transactions
  import Logging
  import Config
  import HttpClient
end
