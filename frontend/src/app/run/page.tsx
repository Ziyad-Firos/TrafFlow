"use client";

import { useEffect, useState } from "react";
import { API, type Network, type RunData } from "@/lib/api";
import { CanvasPlayer } from "@/components/CanvasPlayer";

const metrics = [
  ["J1 throughput", "throughput_vph", "veh/h", 0],
  ["Mean travel time", "mean_travel_time_s", "s", 1],
  ["Mean delay", "mean_delay_s", "s", 1],
  ["Maximum queue", "max_queue", "vehicles", 0],
  ["Mean speed", "mean_speed_mps", "m/s", 1],
] as const;

export default function RunPage() {
  const [runId, setRunId] = useState("");
  const [run, setRun] = useState<RunData | null>(null);
  const [network, setNetwork] = useState<Network | null>(null);
  const [signalGreenS, setSignalGreenS] = useState(54);
  const [error, setError] = useState("");
  useEffect(() => {
    const greenS = Number(new URLSearchParams(window.location.search).get("signal_green_s"));
    if (Number.isFinite(greenS) && greenS > 0 && greenS < 78) setSignalGreenS(greenS);
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) { setError("No run specified."); return; }
    setRunId(id);
    let alive = true;
    fetch(`${API}/runs/${id}/`).then((r) => { if (!r.ok) throw new Error("Run could not be loaded."); return r.json(); })
      .then((data: RunData) => {
        if (!alive) return;
        setRun(data);
        return fetch(`${API}/networks/iisc_two_junctions_v1/?flyover_enabled=${data.summary.spawned_by_route.flyover > 0}`)
          .then((r) => r.json()).then((net: Network) => alive && setNetwork(net));
      }).catch((reason: unknown) => alive && setError(reason instanceof Error ? reason.message : "API unavailable."));
    return () => { alive = false; };
  }, []);

  if (error) return <main className="shell"><p className="api-error">{error}</p><a className="button secondary" href="/">Return home</a></main>;
  if (!run || !network) return <main className="shell"><div className="loading">Loading simulation…</div></main>;
  return <main className="shell">
    <header className="topbar"><a className="brand" href="/"><span className="brand-mark">↗</span><span>TRAFFIC LAB <span className="muted">/ IISc QUEST</span></span></a><div className="top-actions"><a className="button secondary" href="/">New scenario</a><a className="button" href={`/compare?run_a=${runId}`}>Compare runs</a></div></header>
    <div className="run-heading"><div><div className="eyebrow">Completed run · Seed {run.seed}</div><h1>Arterial rush hour</h1><span className="network-badge">{run.engine_version} · {run.summary.duration_s / 60} MIN</span></div><span className="network-badge">{run.summary.spawned_count} vehicles spawned</span></div>
    <nav className="tabs"><a className="tab active" href={`/run?id=${runId}`}>Single</a><a className="tab" href={`/compare?run_a=${runId}`}>Compare</a></nav>
    <CanvasPlayer network={network} frames={run.frames} signalGreenS={signalGreenS} />
    <section className="metrics-grid" aria-label="Simulation metrics">{metrics.map(([label, key, unit, decimals]) => <div className="metric" key={key}><span>{label}</span><strong>{Number(run.summary[key] ?? 0).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}</strong><span>{unit}</span></div>)}</section>
    <p className="footer-note">{run.summary.spawned_by_route.through} through · {run.summary.spawned_by_route.flyover} flyover · {run.summary.overlap_violations} overlap violations · {run.summary.duration_ms} ms engine time</p>
  </main>;
}
