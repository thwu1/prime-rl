# frozen_string_literal: true
# typed: strict

class PaymentGateway < PackageSpec
  # Abstraction over external payment processor APIs.
  # Handles tokenization, charge creation, and settlement.
  layer 'power'
  strict_dependencies 'layered'

  import HttpClient
  import Logging
  import Config
  import Crypto
end
