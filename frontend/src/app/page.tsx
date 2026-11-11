"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { API, type Network } from "@/lib/api";

type Scenario = {
  schema_version: string; network_id: string; network_options: { flyover_enabled: boolean };
  duration_s: number; dt_s: number; record_interval_s: number; seed: number;
  demand: { origin_node: string; destination_node: string; vehicles_per_hour: number; start_s: number; end_s: number; vehicle_type: string; route_share: Record<string, number> }[];
  signals: { node_id: string; cycle_s: number; green_s: number; yellow_s: number; red_s: number; offset_s: number; controlled_edges?: string[] }[];
  vehicle_types: Record<string, Record<string, number>>; events: unknown[];
};

export default function HomePage() {
  const router = useRouter();
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [network, setNetwork] = useState<Network | null>(null);
  const [demand, setDemand] = useState(4500);
  const [greenSplit, setGreenSplit] = useState(54 / 78);
  const [flyover, setFlyover] = useState(true);
  const [seed, setSeed] = useState(20261110);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    Promise.all([
      fetch(`${API}/scenarios/`).then((r) => { if (!r.ok) throw new Error("Could not load preset scenario."); return r.json(); }),
      fetch(`${API}/networks/iisc_two_junctions_v1/`).then((r) => { if (!r.ok) throw new Error("Could not load network preset."); return r.json(); }),
    ]).then(([scenarios, net]) => {
      if (!alive) return;
      const preset = scenarios[0].scenario as Scenario;
      setScenario(preset); setNetwork(net as Network);
      setDemand(preset.demand[0].vehicles_per_hour);
      setFlyover(preset.network_options.flyover_enabled);
      const signal = preset.signals.find((s) => s.node_id === "J1");
      if (signal) setGreenSplit(signal.green_s / (signal.cycle_s - signal.yellow_s));
    }).catch((reason: unknown) => alive && setError(reason instanceof Error ? reason.message : "API unavailable."));
    return () => { alive = false; };
  }, []);

  async function runSimulation() {
    if (!scenario) return;
    setBusy(true); setError("");
    const adjusted: Scenario = structuredClone(scenario);
    adjusted.seed = seed;
    adjusted.duration_s = 300;
    adjusted.network_options.flyover_enabled = flyover;
    adjusted.demand[0].vehicles_per_hour = demand;
    adjusted.demand[0].end_s = adjusted.duration_s;
    for (const signal of adjusted.signals) {
      const green = Math.round(greenSplit * (signal.cycle_s - signal.yellow_s) * 100) / 100;
      signal.green_s = green;
      signal.red_s = signal.cycle_s - signal.yellow_s - green;
    }
    try {
      const response = await fetch(`${API}/runs/`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario_json: adjusted, seed }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? JSON.stringify(body));
      router.push(`/run/${body.run_id}?signal_green_s=${adjusted.signals[0]?.green_s ?? 54}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Run could not be completed.");
    } finally { setBusy(false); }
  }

  return <main className="shell">
    <header className="topbar"><a className="brand" href="/"><span className="brand-mark">↗</span><span>TRAFFIC LAB <span className="muted">/ IISc QUEST</span></span></a><div className="top-actions"><span className="network-badge">AGENT-BASED MODEL · V1</span><a className="button secondary" href="/compare">Compare runs</a></div></header>
    <section className="hero">
      <div><div className="eyebrow">Urban mobility, made observable</div><h1>See how small choices reshape traffic.</h1><p>Configure a demand scenario on the IISc two-junction network, run a deterministic traffic simulation, and inspect how queues and routes evolve.</p></div>
      <div className="hero-art" aria-hidden="true"><svg viewBox="0 0 600 240" fill="none"><path d="M40 120H560" stroke="#55716d" strokeWidth="34"/><path d="M40 120H560" stroke="#c1d1c9" strokeOpacity=".65" strokeWidth="1.5" strokeDasharray="12 14"/><path d="M270 20V220M420 20V220" stroke="#607a75" strokeWidth="17"/><path d="M270 20V220M420 20V220" stroke="#d0d8d2" strokeOpacity=".55" strokeDasharray="7 10"/><path d="M190 103C230 103 220 65 270 65H420C470 65 460 103 505 103" stroke="#72a8b2" strokeWidth="9"/><circle cx="270" cy="120" r="10" fill="#e2a64c"/><circle cx="420" cy="120" r="10" fill="#e2a64c"/><circle cx="126" cy="120" r="6" fill="#8ed9b1"/><circle cx="151" cy="120" r="6" fill="#8ed9b1"/><circle cx="175" cy="120" r="6" fill="#8ed9b1"/><circle cx="330" cy="65" r="6" fill="#8ed9b1"/><circle cx="355" cy="65" r="6" fill="#8ed9b1"/><text x="251" y="154" fill="#9caaa5" fontSize="12">J1</text><text x="402" y="154" fill="#9caaa5" fontSize="12">J2</text></svg></div>
    </section>
    <div className="section-title"><div><div className="eyebrow">Preset network</div><h2>IISc two-junction arterial</h2></div><span className="network-badge">FIXED GEOMETRY · EDIT SCENARIO ONLY</span></div>
    <div className="scenario-layout">
      <section className="card panel">
        <h3>Scenario controls</h3>
        <div className="field"><div style={{ display: "flex", justifyContent: "space-between" }}><label htmlFor="demand">Arterial demand</label><span className="field-value">{demand.toLocaleString()} veh/h</span></div><input id="demand" type="range" min={500} max={6000} step={100} value={demand} onChange={(e) => setDemand(Number(e.target.value))} /></div>
        <div className="field"><div style={{ display: "flex", justifyContent: "space-between" }}><label htmlFor="green">Signal green split</label><span className="field-value">{Math.round(greenSplit * 100)}%</span></div><input id="green" type="range" min={0.35} max={0.75} step={0.01} value={greenSplit} onChange={(e) => setGreenSplit(Number(e.target.value))} /></div>
        <div className="toggle-row"><span>Use the two-lane flyover</span><input aria-label="Use flyover" type="checkbox" checked={flyover} onChange={(e) => setFlyover(e.target.checked)} /></div>
        <div className="field"><label htmlFor="seed">Random seed</label><input id="seed" className="select" type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></div>
        <button className="button full" onClick={runSimulation} disabled={!scenario || busy}>{busy ? "Running simulation…" : "Run baseline"}</button>
        {error && <p className="api-error" role="alert">{error}</p>}
      </section>
      <section className="card network-card">
        <div><div className="eyebrow">Scenario preview</div><p className="muted">Vehicles choose between the signalized arterial and the optional grade-separated route. Compare their impact on travel time and queues.</p></div>
        <div className="network-info">
          <div className="stat"><strong>{network?.nodes.length ?? "—"}</strong><span>junctions & nodes</span></div>
          <div className="stat"><strong>{network?.edges.length ?? "—"}</strong><span>directed roads</span></div>
          <div className="stat"><strong>{network?.edges.find((edge) => edge.id === "a_w_d1")?.lanes ?? "—"}</strong><span>arterial lanes</span></div>
          <div className="stat"><strong>{network?.edges.find((edge) => edge.id === "a_w_d1")?.speed_limit ?? "—"}</strong><span>speed limit · m/s</span></div>
        </div>
      </section>
    </div>
    <p className="footer-note">Fixed 5-minute run · dt 0.1 s · results recorded at 2 Hz · seeded runs are reproducible</p>
  </main>;
}
