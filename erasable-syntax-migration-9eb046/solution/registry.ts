
import { Protocol, MessageType } from "./protocol";
import { Transport, TransportPool } from "./transport";

// ServiceEntry: was namespace Registry { export interface ServiceEntry }
// Interface is type-only and thus erasable — moved to module level
export interface ServiceEntry {
    name: string;
    protocol: Protocol;
    messageTypes: MessageType[];
}

// Registry: was namespace Registry { export function createEntry }
// Replaced with const object to preserve Registry.createEntry() API
export const Registry = {
    createEntry(name: string, protocol: Protocol): ServiceEntry {
        return { name, protocol, messageTypes: [] };
    },
};

// ServiceRegistry: parameter property 'private name' expanded
export class ServiceRegistry {
    private services: Map<string, ServiceEntry> = new Map();
    private pool: TransportPool;
    private name: string;

    constructor(name: string, poolSize: number = 5) {
        this.name = name;
        this.pool = new Transport.Pool(poolSize);
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
