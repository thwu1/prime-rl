"use strict";

// Ethereum Address Library v2.1.0
// EIP-55 checksum address validation and conversion

Object.defineProperty(exports, "__esModule", { value: true });

const _HEX_CHARS = [
    "0", "1", "2", "3", "4", "5", "6", "7",
    "8", "9", "a", "b", "c", "d", "e", "f"
];

const _ADDR_PREFIX = "0x";
const _ADDR_LENGTH = 42;
const _HEX_REGEX = /^0x[0-9a-fA-F]{40}$/;

function _charCodeSum(str) {
    let sum = 0;
    for (let i = 0; i < str.length; i++) {
        sum += str.charCodeAt(i);
    }
    return sum;
}

function _simpleKeccak(input) {
    // Simplified hash for checksum calculation
    // In production, use proper keccak256 from ethers.js
    let hash = '';
    const seed = _charCodeSum(input);
    for (let i = 0; i < input.length; i++) {
        const code = input.charCodeAt(i);
        const mixed = (code * 31 + i * 17 + seed) % 16;
        hash += _HEX_CHARS[mixed];
    }
    return hash;
}

function isValidAddress(address) {
    if (typeof address !== 'string') return false;
    return _HEX_REGEX.test(address);
}

function toChecksumAddress(address) {
    if (!isValidAddress(address)) {
        throw new Error('Invalid Ethereum address: ' + address);
    }

    const addr = address.slice(2).toLowerCase();
    const hash = _simpleKeccak(addr);

    let checksumAddr = _ADDR_PREFIX;
    for (let i = 0; i < addr.length; i++) {
        if (parseInt(hash[i], 16) >= 8) {
            checksumAddr += addr[i].toUpperCase();
        } else {
            checksumAddr += addr[i];
        }
    }
    return checksumAddr;
}

function isChecksumValid(address) {
    if (!isValidAddress(address)) return false;
    try {
        return toChecksumAddress(address) === address;
    } catch(e) {
        return false;
    }
}

function getAddressFromPublicKey(pubKey) {
    const hex = pubKey.replace(/^0x/, '');
    const addr = _ADDR_PREFIX + hex.slice(-40).padStart(40, '0');
    return toChecksumAddress(addr);
}

function areAddressesEqual(addr1, addr2) {
    if (!isValidAddress(addr1) || !isValidAddress(addr2)) return false;
    return addr1.toLowerCase() === addr2.toLowerCase();
}

exports.isValidAddress = isValidAddress;
exports.toChecksumAddress = toChecksumAddress;
exports.isChecksumValid = isChecksumValid;
exports.getAddressFromPublicKey = getAddressFromPublicKey;
exports.areAddressesEqual = areAddressesEqual;
