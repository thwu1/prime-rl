
import { Protocol, Flags } from "./protocol";

// Connection class: parameter properties expanded to explicit declarations
export class Connection {
    public readonly host: string;
    public readonly port: number;
    private protocol: Protocol;
    protected flags: number;

    constructor(
        host: string,
        port: number,
        protocol: Protocol,
        flags: number = Flags.None,
    ) {
        this.host = host;
        this.port = port;
        this.protocol = protocol;
        this.flags = flags;
    }

    getProtocol(): Protocol {
        return this.protocol;
    }

    isCompressed(): boolean {
        return (this.flags & Flags.Compressed) !== 0;
    }

    isEncrypted(): boolean {
        return (this.flags & Flags.Encrypted) !== 0;
    }

    describe(): string {
        return `${this.host}:${this.port} [${Protocol.toName(this.protocol)}]`;
    }
}

// TransportPool: was namespace Transport { export class Pool }
// Parameter property expanded, class moved to module level
export class TransportPool {
    private connections: Connection[] = [];
    private maxSize: number;

    constructor(maxSize: number) {
        this.maxSize = maxSize;
    }

    getMaxSize(): number {
        return this.maxSize;
    }

    add(conn: Connection): boolean {
        if (this.connections.length >= this.maxSize) return false;
        this.connections.push(conn);
        return true;
    }

    size(): number {
        return this.connections.length;
    }
}

// Namespace replacement: const object preserving Transport.Pool and Transport.createDefault() API
export const Transport = {
    Pool: TransportPool,
    createDefault(): TransportPool {
        return new TransportPool(10);
    },
};
