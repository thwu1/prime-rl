# frozen_string_literal: true
# typed: strict

class Merchants < PackageSpec
  # Merchant accounts, onboarding, KYC verification,
  # and payout configuration.
  layer 'business'
  strict_dependencies 'layered'

  import Database
  import Logging
  import Config
  import PaymentGateway
  import EmailProvider
end
