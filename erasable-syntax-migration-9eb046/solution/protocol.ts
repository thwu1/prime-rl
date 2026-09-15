
// Helper: replicates TypeScript's numeric enum runtime behavior.
// Creates bidirectional mapping: name→value AND value→name (for numeric values only).
function createEnum<T extends Record<string, string | number>>(
    values: T
): T & { [k: number]: string } {
    const result: any = { ...values };
    for (const [key, value] of Object.entries(values)) {
        if (typeof value === "number") {
            result[value] = key;
        }
    }
    return result;
}

// --- Protocol (was: numeric enum + merged namespace) ---

const _Protocol = createEnum({
    HTTP: 1 as const,
    HTTPS: 2 as const,
    WS: 3 as const,
    WSS: 4 as const,
});

export const Protocol = Object.assign(_Protocol, {
    isSecure(p: number): boolean {
        return p === _Protocol.HTTPS || p === _Protocol.WSS;
    },
    toName(p: number): string {
        return (_Protocol as any)[p];
    },
    allNames(): string[] {
        return Object.keys(_Protocol).filter(
            (k) => typeof (_Protocol as any)[k] === "number"
        );
    },
});

export type Protocol = 1 | 2 | 3 | 4;

// --- MessageType (was: string enum — no reverse mapping) ---

export const MessageType = {
    Request: "REQ",
    Response: "RES",
    Notification: "NOTIFY",
} as const;

export type MessageType = (typeof MessageType)[keyof typeof MessageType];

// --- Flags (was: const enum — values were inlined at compile time) ---

export const Flags = {
    None: 0,
    Compressed: 1, // 1 << 0
    Encrypted: 2, // 1 << 1
    Signed: 4, // 1 << 2
    All: 7, // 1 | 2 | 4
} as const;

export type Flags = (typeof Flags)[keyof typeof Flags];

// --- LogLevel (was: heterogeneous enum + merged namespace) ---
// Numeric members get reverse mapping; string members do NOT.

const _LogLevel = createEnum({
    Debug: 0 as const,
    Info: 1 as const,
    Warn: 2 as const,
    Error: "ERROR" as const,
    Fatal: "FATAL" as const,
});

export const LogLevel = Object.assign(_LogLevel, {
    isNumeric(level: number | string): boolean {
        return typeof level === "number";
    },
    getNumericName(level: number): string | undefined {
        return (_LogLevel as any)[level];
    },
});

export type LogLevel = 0 | 1 | 2 | "ERROR" | "FATAL";
