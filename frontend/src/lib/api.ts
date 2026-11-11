export const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api").replace(/\/$/, "");

export type Network = {
  id: string; schema_version: string;
  nodes: { id: string; x: number; y: number; type: string }[];
  edges: { id: string; from_node: string; to_node: string; length: number; lanes: number; speed_limit: number; polyline: [number, number][]; type: string }[];
  connections: { from_edge: string; to_edge: string; lanes: (number | null)[] }[];
};
export type Frames = { t: number[]; id: number[]; edge: string[]; s: number[]; lane: number[]; v: number[] };
export type RunSummary = {
  [key: string]: number | string | { through: number; flyover: number };
  spawned_by_route: { through: number; flyover: number };
  duration_s: number; spawned_count: number; overlap_violations: number; duration_ms: number;
};
export type RunData = { schema_version: string; engine_version: string; seed: number; frames_format: string; summary: RunSummary; frames: Frames };
