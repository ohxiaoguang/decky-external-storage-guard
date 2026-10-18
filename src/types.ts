export type Action = "mount" | "unmount";
export interface Partition {
  name: string; path: string; size: number; filesystem: string | null; readOnly: boolean;
  mounts: { target: string; readOnly: boolean }[];
  actions: Record<Action, { token: string | null; reason: string }>;
}
export interface Device {
  id: string; name: string; model: string; size: number; kind: string;
  mounted: boolean; readOnly: boolean; partitions: Partition[];
}
export interface Operation {
  status: string; action: Action; phase?: string; target?: string | null;
  message: string; verified: boolean; returncode?: number | null;
  mounts?: { target: string; readOnly: boolean }[] | null; readOnly?: boolean | null;
}
export interface Snapshot {
  devices: Device[]; deviceStatus: { status: string; message: string }; lastOperation: Operation | null;
}
export interface OperationResponse { operation: Operation; snapshot: Snapshot | null }
export interface Logs { status: string; message: string; text: string; limited: boolean }
