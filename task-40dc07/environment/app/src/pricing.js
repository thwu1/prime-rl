const { featureToggle } = require('./utils/featureToggle');

function getDiscount() {
  return featureToggle('feature-pricing-v2') ? 0.15 : 0.10;
}

function getShippingRate() {
  return featureToggle('feature-free-shipping') ? 0 : 5.99;
}

module.exports = { getDiscount, getShippingRate };
