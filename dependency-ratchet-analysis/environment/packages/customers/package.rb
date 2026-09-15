# frozen_string_literal: true
# typed: strict

class Customers < PackageSpec
  # Customer profiles, saved payment methods,
  # and communication preferences.
  layer 'business'
  strict_dependencies 'layered'

  import Database
  import Logging
  import Config
  import Merchants
end
