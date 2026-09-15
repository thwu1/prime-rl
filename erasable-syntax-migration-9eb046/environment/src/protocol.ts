// Protocol state definitions for the RPC framework

export enum Protocol {
    HTTP = 1,
    HTTPS = 2,
    WS = 3,
    WSS = 4,
}

export namespace Protocol {
    export function isSecure(p: Protocol): boolean {
        return p === Protocol.HTTPS || p === Protocol.WSS;
    }

    export function toName(p: Protocol): string {
        return Protocol[p];
    }

    export function allNames(): string[] {
        return Object.keys(Protocol).filter(
            (k) => typeof (Protocol as any)[k] === "number"
        );
    }
}

export enum MessageType {
    Request = "REQ",
    Response = "RES",
    Notification = "NOTIFY",
}

export const enum Flags {
    None = 0,
    Compressed = 1 << 0,
    Encrypted = 1 << 1,
    Signed = 1 << 2,
    All = Compressed | Encrypted | Signed,
}

export enum LogLevel {
    Debug = 0,
    Info = 1,
    Warn = 2,
    Error = "ERROR",
    Fatal = "FATAL",
}

export namespace LogLevel {
    export function isNumeric(level: LogLevel): boolean {
        return typeof level === "number";
    }

    export function getNumericName(level: number): string | undefined {
        return (LogLevel as any)[level];
    }
}
