export type Severity = "Error" | "Warning" | "Info";
export type Window = "boot" | "day" | "week" | "all" | "previous";
export interface WakeContext {
  phase: "unknown" | "before_suspend" | "during_unknown" | "after_wake";
  cycleId: string | null; delaySeconds: number | null; estimated: boolean;
  basis: string; beforeNextSuspend: boolean; clockAdjusted?: boolean;
}
export interface SleepPoint { timestamp: number | null; realtimeUs: number | null; monotonicUs: number | null }
export interface TimelineEntry extends SleepPoint {
  source: "sleep" | "storage"; eventId?: string; message?: string; kind: string; phase: string; estimated: boolean;
}
export interface SleepCycle {
  id: string; bootId: string; start: SleepPoint | null; wake: SleepPoint | null;
  status: string; completion: string | null; estimated: boolean; notes: string[];
  timeline?: TimelineEntry[];
  records: { timestamp: number | null; message: string; kind: string }[];
  afterCounts: Record<string, number>; observations: string[]; traceLimited: boolean;
}
export interface SleepHistory { cycles: SleepCycle[]; status: string; limited: boolean; message: string }
export interface DiagnosticReport {
  status: string; message?: string; reportId?: string; text?: string; summary?: string;
  size?: number; truncated?: boolean; generatedAt?: number; rawCount?: number;
}
export interface ReadStatus { status: string; message: string; limited?: boolean }
export interface Partition {
  name: string; path: string; size: number; filesystem: string | null; readOnly: boolean;
  mounts: { target: string; filesystem: string | null; readOnly: boolean }[];
  management?: { eligible: boolean; reason: string; token: string | null; warnings: string[] };
}
export interface Operation {
  status: string; phase: string; message: string; detail: string; partition: string | null;
  unmounted: boolean | null; mounted: boolean | null; warnings: string[]; finishedAt?: number;
  operationId?: string; startedAt?: number; method?: string;
  commands?: { phase: string; returncode: number | null; status: string }[];
  beforeUnmount?: unknown; afterUnmount?: unknown; afterMount?: unknown;
}
export interface RemountResponse { operation: Operation; snapshot: Snapshot | null }
export interface Device {
  id: string; name: string; model: string; size: number; kind: string;
  transport: string | null; topology: string; mounted: boolean; readOnly: boolean;
  partitions: Partition[]; counts: Record<Severity, number>; lastEvent: number | null;
}
export interface StorageEvent {
  id: string; timestamp: number | null; deviceId: string | null; deviceLabel: string | null;
  references: string[]; bootId: string | null; kind: string; severity: Severity; summary: string; raw: string;
  wakeContext?: WakeContext;
}
export interface Snapshot {
  devices: Device[]; deviceStatus: ReadStatus; journalStatus: ReadStatus;
  events: StorageEvent[]; warnings: string[]; window: Window; refreshedAt: number;
  lastOperation: Operation | null;
  sleepHistory?: SleepHistory;
}
