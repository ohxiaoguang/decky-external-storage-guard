export type Severity = "Error" | "Warning" | "Info";
export type Window = "boot" | "day" | "previous";
export interface ReadStatus { status: string; message: string; limited?: boolean }
export interface Partition {
  name: string; path: string; size: number; filesystem: string | null; readOnly: boolean;
  mounts: { target: string; filesystem: string | null; readOnly: boolean }[];
}
export interface Device {
  id: string; name: string; model: string; size: number; kind: string;
  transport: string | null; topology: string; mounted: boolean; readOnly: boolean;
  partitions: Partition[]; counts: Record<Severity, number>; lastEvent: number | null;
}
export interface StorageEvent {
  id: string; timestamp: number | null; deviceId: string | null; deviceLabel: string | null;
  references: string[]; bootId: string | null; kind: string; severity: Severity; summary: string; raw: string;
}
export interface Snapshot {
  devices: Device[]; deviceStatus: ReadStatus; journalStatus: ReadStatus;
  events: StorageEvent[]; warnings: string[]; window: Window; refreshedAt: number;
}
