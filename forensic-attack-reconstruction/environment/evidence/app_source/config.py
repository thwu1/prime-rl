"""Application configuration for AcmeCorp Product Catalog."""
import os

# Flask settings
SECRET_KEY = 'acme-flask-s3cr3t-k3y-d0-n0t-sh4r3'
DEBUG = False
APP_VERSION = '3.2.1'

# Database
DATABASE_URI = 'sqlite:///products.db'

# Service account credentials (used by the app to connect to internal services)
SERVICE_USER = 'devops'
SERVICE_PASSWORD = 'D3v0ps_Autumn#2024!'

# Mail settings
MAIL_SERVER = 'mail.internal.acmecorp.com'
MAIL_PORT = 587
MAIL_USERNAME = 'noreply@acmecorp.com'
MAIL_PASSWORD = 'M41l_s3rv1c3_pw'

# Logging
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
LOG_FILE = '/var/log/acmecorp/app.log'
