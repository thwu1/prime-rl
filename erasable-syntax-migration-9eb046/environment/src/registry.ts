import { Protocol, MessageType } from "./protocol";
import { Transport } from "./transport";

import TransportPool = Transport.Pool;

namespace Registry {
    export interface ServiceEntry {
        name: string;
        protocol: Protocol;
        messageTypes: MessageType[];
    }

    export function createEntry(
        name: string,
        protocol: Protocol
    ): ServiceEntry {
        return { name, protocol, messageTypes: [] };
    }
}

import ServiceEntry = Registry.ServiceEntry;

export class ServiceRegistry {
    private services: Map<string, ServiceEntry> = new Map();
    private pool: TransportPool;

    constructor(
        private name: string,
        poolSize: number = 5,
    ) {
        this.pool = new TransportPool(poolSize);
    }

    register(entry: ServiceEntry): void {
        this.services.set(entry.name, entry);
    }

    getEntry(name: string): ServiceEntry | undefined {
        return this.services.get(name);
    }

    getPool(): TransportPool {
        return this.pool;
    }

    getRegistryName(): string {
        return this.name;
    }

    getServiceCount(): number {
        return this.services.size;
    }
}

export { Registry };
