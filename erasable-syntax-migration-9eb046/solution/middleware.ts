
import { Protocol } from "./protocol";

abstract class TrackedComponent {
    #mutations: Array<{ prop: string; from: unknown; to: unknown }> = [];
    #propStore: Record<string, unknown> = {};

    constructor(trackedProps: string[]) {
        for (const propName of trackedProps) {
            this.#propStore[propName] = null;
            Object.defineProperty(this, propName, {
                get: () => this.#propStore[propName],
                set: (v: unknown) => {
                    const from = this.#propStore[propName];
                    this.#mutations.push({ prop: propName, from, to: v });
                    this.#propStore[propName] = v;
                },
                enumerable: true,
                configurable: true,
            });
        }
    }

    getMutations(): Array<{ prop: string; from: unknown; to: unknown }> {
        return [...this.#mutations];
    }

    getMutationCount(): number {
        return this.#mutations.length;
    }
}

// Interface-class declaration merge: declares the tracked property types on
// Middleware instances without emitting class field initializers. This prevents
// ES2022 [[DefineOwnProperty]] from overwriting TrackedComponent's dynamically
// installed getter/setters. The non-tracked protocol uses ES private syntax (#)
// which safely coexists with the tracked property descriptors.
export interface Middleware {
    name: string;
    priority: number;
}

export class Middleware extends TrackedComponent {
    #protocol: Protocol;

    constructor(name: string, priority: number, protocol: Protocol) {
        super(["name", "priority"]);
        this.name = name;
        this.priority = priority;
        this.#protocol = protocol;
    }

    getProtocol(): Protocol {
        return this.#protocol;
    }

    describe(): string {
        return `[${this.priority}] ${this.name}`;
    }

    static create(
        name: string,
        priority: number,
        protocol: Protocol,
    ): Middleware {
        return new Middleware(name, priority, protocol);
    }

    static sortByPriority(items: Middleware[]): Middleware[] {
        return [...items].sort(
            (a, b) => a.priority - b.priority
        );
    }
}
