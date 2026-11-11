"use client";

import { useEffect, useState } from "react";
import { API } from "@/lib/api";

type RunItem = { run_id: string; status: string; created_at: string; summary: Record<string, number> };
const comparisons = [
  ["J1 throughput", "throughput_vph", "veh/h", true],
  ["Mean travel time", "mean_travel_time_s", "s", false],
  ["Mean delay", "mean_delay_s", "s", false],
  ["Maximum queue", "max_queue", "vehicles", false],
  ["Mean speed", "mean_speed_mps", "m/s", true],
] as const;

function format(value: number, unit: string) { return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} ${unit}`; }

export default function ComparePage() {
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    setA(query.get("run_a") ?? ""); setB(query.get("run_b") ?? "");
    fetch(`${API}/runs/`).then((r) => r.json()).then(setRuns).catch(() => setError("Could not load saved runs."));
  }, []);
  const runA = runs.find((run) => run.run_id === a), runB = runs.find((run) => run.run_id === b);
  return <main className="shell">
    <header className="topbar"><a className="brand" href="/"><span className="brand-mark">↗</span><span>TRAFFIC LAB <span className="muted">/ IISc QUEST</span></span></a><a className="button secondary" href="/">New scenario</a></header>
    <div className="eyebrow">Side-by-side analysis</div><h1 style={{ fontSize: 34, margin: "8px 0 20px" }}>Compare two runs</h1>
    <div className="compare-head"><label className="card">Run A<select className="select" value={a} onChange={(e) => setA(e.target.value)}><option value="">Choose a completed run</option>{runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.created_at} · {run.run_id.slice(0, 8)}</option>)}</select></label><label className="card">Run B<select className="select" value={b} onChange={(e) => setB(e.target.value)}><option value="">Choose a completed run</option>{runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.created_at} · {run.run_id.slice(0, 8)}</option>)}</select></label></div>
    {error && <p className="api-error">{error}</p>}
    {runA && runB ? <section className="card"><div className="compare-grid"><div><div className="eyebrow">Run A · {a.slice(0, 8)}</div></div><div><div className="eyebrow">Run B · {b.slice(0, 8)}</div></div></div>{comparisons.map(([label, key, unit, higherBetter]) => {
      const av = Number(runA.summary[key] ?? 0), bv = Number(runB.summary[key] ?? 0), delta = av === 0 ? 0 : ((bv - av) / Math.abs(av)) * 100;
      const favorable = higherBetter ? delta > 0 : delta < 0;
      return <div className="metric-delta" key={key}><span>{label}</span><span className="mono">{format(av, unit)}　→　{format(bv, unit)}</span><strong className={favorable ? "positive" : "negative"}>{delta > 0 ? "+" : ""}{delta.toFixed(1)}%</strong></div>;
    })}</section> : <section className="card muted">Select two completed runs to compare throughput, travel time, delay, queue length, and speed.</section>}
  </main>;
}
