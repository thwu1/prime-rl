const { featureToggle } = require('./utils/featureToggle');

function getTrackingEndpoint() {
  const isPricingV2 = featureToggle('feature-pricing-v2');

  if (isPricingV2) {
    return '/v2/track';
  } else {
    return '/v1/track';
  }
}

module.exports = { getTrackingEndpoint };
