# frozen_string_literal: true
# typed: strict

class EmailProvider < PackageSpec
  # Email delivery via multiple providers (SES, SendGrid, etc).
  # Includes template rendering and delivery tracking.
  layer 'power'
  strict_dependencies 'false'

  import HttpClient
  import Logging
  import Config
  import Merchants  # merchant branding in email templates
end
