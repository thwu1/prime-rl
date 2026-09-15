'use strict';

const http = require('http');
const configFlatten = require('./lib/config-flatten');
const cmdBuilder = require('./lib/cmd-builder');
const inputValidator = require('./lib/input-validator');
const archiveUtils = require('./lib/archive-utils');
const telemetry = require('./lib/telemetry-helper');

const PORT = process.env.PORT || 3000;

const telemetryClient = telemetry.createClient({
  flushInterval: 30000,
  batchSize: 50,
});

function readBody(req) {
  return new Promise(function(resolve, reject) {
    var body = '';
    req.on('data', function(chunk) { body += chunk; });
    req.on('end', function() { resolve(body); });
    req.on('error', reject);
  });
}

var server = http.createServer(function(req, res) {
  readBody(req).then(function(body) {
    telemetryClient.track('request', { method: req.method, path: req.url });

    if (req.url === '/api/config' && req.method === 'POST') {
      var data = JSON.parse(body);
      var result;
      if (data.action === 'flatten') {
        result = configFlatten.flatten(data.config);
      } else if (data.action === 'unflatten') {
        result = configFlatten.unflatten(data.config);
      } else if (data.action === 'merge') {
        result = configFlatten.merge(data.target, data.source);
      }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(result));

    } else if (req.url === '/api/command' && req.method === 'POST') {
      var cmdData = JSON.parse(body);
      var cmd = cmdBuilder.quote(cmdData.args);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ command: cmd }));

    } else if (req.url === '/api/validate' && req.method === 'POST') {
      var valData = JSON.parse(body);
      var results = {};
      if (valData.email) results.email = inputValidator.validateEmail(valData.email);
      if (valData.url) results.url = inputValidator.validateUrl(valData.url);
      if (valData.selector) results.selector = inputValidator.validateSelector(valData.selector);
      if (valData.html) results.sanitized = inputValidator.sanitizeHtml(valData.html);
      if (valData.username) results.username = inputValidator.validateUsername(valData.username);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(results));

    } else if (req.url === '/api/archive/extract' && req.method === 'POST') {
      var archData = JSON.parse(body);
      var archResult = archiveUtils.extractArchive(archData.entries, archData.destDir || '/tmp/extract');
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(archResult));

    } else if (req.url === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok', uptime: process.uptime() }));

    } else {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Not found' }));
    }
  }).catch(function(err) {
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: err.message }));
  });
});

if (require.main === module) {
  telemetryClient.start();
  server.listen(PORT, function() {
    console.log('Server running on port ' + PORT);
  });
}

module.exports = server;
