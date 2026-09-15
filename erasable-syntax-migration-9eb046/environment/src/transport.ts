import { Protocol, Flags } from "./protocol";

export class Connection {
    constructor(
        public readonly host: string,
        public readonly port: number,
        private protocol: Protocol,
        protected flags: number = Flags.None,
    ) {}

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

export namespace Transport {
    export class Pool {
        private connections: Connection[] = [];

        constructor(private maxSize: number) {}

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

    export function createDefault(): Pool {
        return new Pool(10);
    }
}
