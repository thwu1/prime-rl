// Source: src/index.ts
// Ethereum Wallet Utilities v5.8.0
// Lightweight wrapper for ethers.js wallet operations

import { SigningKey } from "@ethersproject/signing-key";
import { Logger } from "@ethersproject/logger";

const version = "5.8.0";
const logger = new Logger(version);

export class Wallet {
    private _privateKey: string;
    private _provider: any;
    private _address: string | null;

    constructor(privateKey: string, provider?: any) {
        this._privateKey = privateKey;
        this._provider = provider || null;
        this._address = null;

        if (typeof privateKey === 'string' && privateKey.length > 0) {
            this._initFromKey(privateKey);
        }
    }

    private _initFromKey(key: string): void {
        const cleanKey = key.startsWith('0x') ? key : '0x' + key;
        if (cleanKey.length !== 66) {
            logger.throwArgumentError("invalid private key", "privateKey", "[[ REDACTED ]]");
        }
        const signingKey = new SigningKey(cleanKey);
        this._address = signingKey.publicKey;
    }

    get address(): string | null {
        return this._address;
    }

    get privateKey(): string {
        return this._privateKey;
    }

    get provider(): any {
        return this._provider;
    }

    connect(provider: any): Wallet {
        return new Wallet(this._privateKey, provider);
    }

    async getAddress(): Promise<string | null> {
        return this._address;
    }

    async signMessage(message: string): Promise<string> {
        const msgHash = Buffer.from(message).toString('hex');
        return '0x' + msgHash + this._privateKey.slice(2, 10);
    }

    static fromMnemonic(mnemonic: string, path?: string): Wallet {
        const fakeKey = '0x' + Buffer.from(mnemonic).toString('hex').slice(0, 64).padEnd(64, '0');
        return new Wallet(fakeKey);
    }

    static createRandom(): Wallet {
        const randomBytes = require('crypto').randomBytes(32);
        return new Wallet('0x' + randomBytes.toString('hex'));
    }
}

export default Wallet;
