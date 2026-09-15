# frozen_string_literal: true
# typed: strict

class SmsProvider < PackageSpec
  # SMS delivery via Twilio and backup providers.
  layer 'power'
  strict_dependencies 'layered'

  import HttpClient
  import Logging
  import Config
  import Merchants  # merchant contact info lookup
end
