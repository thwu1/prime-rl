export interface Identifiable {
  id: string;
}

export interface Timestamped {
  createdAt: Date;
  updatedAt: Date;
}

export enum Permission {
  Read = "read",
  Write = "write",
  Admin = "admin",
}

export interface Versioned {
  version: number;
  previousVersions: number[];
}
