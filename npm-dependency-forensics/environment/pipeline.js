/**
 * Data Processing Pipeline
 *
 * A CLI tool that processes configuration files, transforms JSON data,
 * extracts archives, and filters data using CSS nth-check selectors.
 */

const flat = require('flat');
const tar = require('tar');
const nthCheck = require('nth-check');
const yaml = require('js-yaml');
const fs = require('fs');
const path = require('path');

/**
 * Load and parse a YAML configuration file.
 */
function loadConfig(configPath) {
  const content = fs.readFileSync(configPath, 'utf-8');
  return yaml.load(content);
}

/**
 * Flatten then unflatten a JSON data object for normalization.
 */
function normalizeData(data) {
  const flattened = flat.flatten(data);
  return flat.unflatten(flattened);
}

/**
 * Extract a tar archive to a destination directory.
 */
function extractArchive(archivePath, destDir) {
  fs.mkdirSync(destDir, { recursive: true });
  return tar.x({
    file: archivePath,
    cwd: destDir,
    sync: true,
  });
}

/**
 * Filter an array of items by an nth-check CSS selector formula.
 */
function filterBySelector(items, formula) {
  const checker = nthCheck.default(formula);
  return items.filter((_, index) => checker(index));
}

/**
 * Run the full pipeline: load config, normalize data, extract archive, filter output.
 */
function runPipeline(configPath, dataPath, archivePath, outputDir) {
  const config = loadConfig(configPath);
  const rawData = JSON.parse(fs.readFileSync(dataPath, 'utf-8'));
  const data = normalizeData(rawData);
  extractArchive(archivePath, path.join(outputDir, 'extracted'));
  const selector = config.filter_selector || '2n+1';
  const keys = Object.keys(data);
  const filtered = filterBySelector(keys, selector);
  const result = {};
  for (const k of filtered) {
    result[k] = data[k];
  }
  fs.writeFileSync(path.join(outputDir, 'result.json'), JSON.stringify(result, null, 2));
  return result;
}

module.exports = { loadConfig, normalizeData, extractArchive, filterBySelector, runPipeline };

if (require.main === module) {
  const args = process.argv.slice(2);
  if (args.length < 4) {
    console.log('Usage: node pipeline.js <config.yaml> <data.json> <archive.tar> <output_dir>');
    process.exit(1);
  }
  runPipeline(args[0], args[1], args[2], args[3]);
  console.log('Pipeline complete.');
}
