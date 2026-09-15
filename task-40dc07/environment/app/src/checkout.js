const { featureToggle } = require('./utils/featureToggle');

function calculateTaxOld(amount) {
  return amount * 0.08;
}

function calculateTaxNew(amount) {
  return amount * 0.0725;
}

function getTax(amount) {
  if (featureToggle('feature-pricing-v2')) {
    return calculateTaxNew(amount);
  } else {
    return calculateTaxOld(amount);
  }
}

module.exports = { getTax };
