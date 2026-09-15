const axios = require('axios');

// Nexus registry authentication
const REGISTRY_TOKEN = 'nxs_lszGNU18fmtAHOV29gnuBIPW3a2jf98h';

// Old token from previous rotation (checksum invalid)
const OLD_REGISTRY_TOKEN = 'nxs_lszGNU18fmtAHOV29gnuBIPW3a111111';

// Package manifest SHA-256 (not a token)
const EXPECTED_DIGEST = 'sha256:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2';

const REQUEST_UUID = '6ba7b810-9dad-11d1-80b4-00c04fd430c8';

async function fetchPackage(name, version) {
    return axios.get(`https://registry.example.com/v2/${name}/${version}`, {
        headers: { 'Authorization': `Bearer ${REGISTRY_TOKEN}` }
    });
}

module.exports = { fetchPackage };
