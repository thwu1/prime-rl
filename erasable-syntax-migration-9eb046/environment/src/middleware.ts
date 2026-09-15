import { Protocol } from "./protocol";

abstract class TrackedComponent {
    private _mutations: Array<{ prop: string; from: unknown; to: unknown }> = [];
    private _propStore: Record<string, unknown> = {};

    constructor(trackedProps: string[]) {
        for (const propName of trackedProps) {
            this._propStore[propName] = null;
            Object.defineProperty(this, propName, {
                get: () => this._propStore[propName],
                set: (v: unknown) => {
                    const from = this._propStore[propName];
                    this._mutations.push({ prop: propName, from, to: v });
                    this._propStore[propName] = v;
                },
                enumerable: true,
                configurable: true,
            });
        }
    }

    getMutations(): Array<{ prop: string; from: unknown; to: unknown }> {
        return [...this._mutations];
    }

    getMutationCount(): number {
        return this._mutations.length;
    }
}

export class Middleware extends TrackedComponent {
    constructor(
        public name: string,
        public priority: number,
        private protocol: Protocol,
    ) {
        super(["name", "priority"]);
    }

    getProtocol(): Protocol {
        return this.protocol;
    }

    describe(): string {
        return `[${this.priority}] ${this.name}`;
    }
}

export namespace Middleware {
    export function create(
        name: string,
        priority: number,
        protocol: Protocol,
    ): Middleware {
        return new Middleware(name, priority, protocol);
    }

    export function sortByPriority(items: Middleware[]): Middleware[] {
        return [...items].sort(
            (a, b) => a.priority - b.priority
        );
    }
}
