"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Frames, Network } from "@/lib/api";

type Props = { network: Network; frames: Frames; signalGreenS: number };
type VehicleFrame = { edge: string; s: number; lane: number; v: number };
type Geometry = { cumulative: number[]; lengths: number[]; total: number };
type Transform = (x: number, y: number) => [number, number];
type PerfReadout = { fps: number; renderMs: number; vehicles: number };

const CAR_PALETTE = ["#c0392b", "#2980b9", "#27ae60", "#8e44ad", "#d35400", "#16a085", "#7f8c8d", "#2c3e50"];
const SIGNALS = [
  { node: "J1", cycle: 80, yellow: 2, offset: 0 },
  { node: "J2", cycle: 80, yellow: 2, offset: 20 },
] as const;

function buildGeometry(network: Network) {
  return new Map(network.edges.map((edge) => {
    const lengths = edge.polyline.slice(1).map((point, index) => Math.hypot(point[0] - edge.polyline[index][0], point[1] - edge.polyline[index][1]));
    const cumulative = [0];
    for (const length of lengths) cumulative.push(cumulative[cumulative.length - 1] + length);
    return [edge.id, { cumulative, lengths, total: cumulative[cumulative.length - 1] } satisfies Geometry];
  }));
}

function worldTransform(network: Network, width: number, height: number): Transform {
  const all = network.edges.flatMap((edge) => edge.polyline);
  const minX = Math.min(...all.map((point) => point[0])), maxX = Math.max(...all.map((point) => point[0]));
  const minY = Math.min(...all.map((point) => point[1])), maxY = Math.max(...all.map((point) => point[1]));
  const scale = Math.min(width * 0.9 / Math.max(1, maxX - minX), height * 0.9 / Math.max(1, maxY - minY));
  const centerX = (minX + maxX) / 2, centerY = (minY + maxY) / 2;
  return (x, y) => [width / 2 + (x - centerX) * scale, height / 2 - (y - centerY) * scale];
}

function pointAt(edge: Network["edges"][number], geometry: Geometry, s: number, lane: number): { x: number; y: number; angle: number } {
  const remaining = Math.max(0, Math.min(s, geometry.total));
  let x = edge.polyline[0][0], y = edge.polyline[0][1], dx = 1, dy = 0;
  for (let index = 0; index < geometry.lengths.length; index++) {
    const length = geometry.lengths[index];
    dx = edge.polyline[index + 1][0] - edge.polyline[index][0];
    dy = edge.polyline[index + 1][1] - edge.polyline[index][1];
    if (remaining <= geometry.cumulative[index + 1] || index === geometry.lengths.length - 1) {
      const local = Math.max(0, Math.min(length, remaining - geometry.cumulative[index]));
      const ratio = length === 0 ? 0 : local / length;
      x = edge.polyline[index][0] + dx * ratio;
      y = edge.polyline[index][1] + dy * ratio;
      break;
    }
  }
  const norm = Math.hypot(dx, dy) || 1;
  const offset = (lane - (edge.lanes - 1) / 2) * 3.4;
  return { x: x - (dy / norm) * offset, y: y + (dx / norm) * offset, angle: Math.atan2(-dy, dx) };
}

function offsetPolyline(points: [number, number][], transform: Transform, offset: number) {
  const screen = points.map(([x, y], index) => {
    const previous = points[Math.max(0, index - 1)], next = points[Math.min(points.length - 1, index + 1)];
    const dx = next[0] - previous[0], dy = next[1] - previous[1], length = Math.hypot(dx, dy) || 1;
    return transform(x - (dy / length) * offset, y + (dx / length) * offset);
  });
  return screen;
}

function strokeRoadPath(ctx: CanvasRenderingContext2D, points: [number, number][], transform: Transform) {
  ctx.beginPath();
  points.forEach(([x, y], index) => {
    const point = transform(x, y);
    if (index === 0) ctx.moveTo(point[0], point[1]); else ctx.lineTo(point[0], point[1]);
  });
}

function drawRoadMarkings(ctx: CanvasRenderingContext2D, edge: Network["edges"][number], transform: Transform) {
  const dividerCount = Math.max(0, edge.lanes - 1);
  if (dividerCount > 0) {
    ctx.save(); ctx.strokeStyle = "rgba(236, 239, 231, .62)"; ctx.lineWidth = 1; ctx.setLineDash([5, 7]);
    for (let divider = 0; divider < dividerCount; divider++) {
      const offset = (divider - (edge.lanes - 1) / 2 + 0.5) * 4.4;
      const points = offsetPolyline(edge.polyline, transform, offset);
      ctx.beginPath(); points.forEach(([x, y], index) => index === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)); ctx.stroke();
    }
    ctx.restore();
  }
  if (edge.lanes > 1 && edge.type !== "ramp") {
    strokeRoadPath(ctx, edge.polyline, transform);
    ctx.save(); ctx.strokeStyle = "#e2bd57"; ctx.globalAlpha = 0.9; ctx.lineWidth = 1.2; ctx.setLineDash([8, 8]); ctx.stroke(); ctx.restore();
  }
}

function drawStreetlights(ctx: CanvasRenderingContext2D, network: Network, transform: Transform) {
  const seen = new Set<string>();
  for (const edge of network.edges) {
    if (edge.type === "ramp") continue;
    const forward = JSON.stringify(edge.polyline), reverse = JSON.stringify([...edge.polyline].reverse());
    const key = forward < reverse ? forward : reverse;
    if (seen.has(key)) continue;
    seen.add(key);
    const geometry = edge.polyline.slice(1).map((point, index) => Math.hypot(point[0] - edge.polyline[index][0], point[1] - edge.polyline[index][1]));
    let traveled = 0, nextLamp = 50;
    for (let segment = 0; segment < geometry.length; segment++) {
      const length = geometry[segment], from = edge.polyline[segment], to = edge.polyline[segment + 1];
      while (nextLamp < traveled + length) {
        const fraction = (nextLamp - traveled) / length;
        const x = from[0] + (to[0] - from[0]) * fraction, y = from[1] + (to[1] - from[1]) * fraction;
        const dx = to[0] - from[0], dy = to[1] - from[1], norm = Math.hypot(dx, dy) || 1;
        const point = transform(x - (dy / norm) * 15, y + (dx / norm) * 15);
        const glow = ctx.createRadialGradient(point[0], point[1], 0, point[0], point[1], 8);
        glow.addColorStop(0, "rgba(243,156,18,.35)"); glow.addColorStop(1, "rgba(243,156,18,0)");
        ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(point[0], point[1], 8, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = "rgba(193, 203, 189, .8)"; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(point[0], point[1] + 1); ctx.lineTo(point[0] + 1, point[1] + 6); ctx.stroke();
        ctx.fillStyle = "#f39c12"; ctx.beginPath(); ctx.arc(point[0], point[1], 1.5, 0, Math.PI * 2); ctx.fill();
        nextLamp += 50;
      }
      traveled += length;
    }
  }
}

function drawStaticLayer(ctx: CanvasRenderingContext2D, network: Network, transform: Transform, width: number, height: number) {
  const background = ctx.createLinearGradient(0, 0, width, height);
  background.addColorStop(0, "#14211f"); background.addColorStop(0.54, "#172123"); background.addColorStop(1, "#11191c");
  ctx.fillStyle = background; ctx.fillRect(0, 0, width, height);
  // A restrained ground grid gives the network scale without competing with traffic.
  ctx.save(); ctx.strokeStyle = "rgba(159,183,168,.035)"; ctx.lineWidth = 1;
  for (let x = 20; x < width; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke(); }
  for (let y = 20; y < height; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke(); }
  ctx.restore();

  const drawEdge = (edge: Network["edges"][number]) => {
    const widthPx = edge.type === "flyover" ? 16 : edge.type === "ramp" ? 8 : Math.max(12, edge.lanes * 7);
    strokeRoadPath(ctx, edge.polyline, transform);
    ctx.save(); ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "#202b2d"; ctx.lineWidth = widthPx + 4; ctx.stroke(); ctx.restore();
    strokeRoadPath(ctx, edge.polyline, transform);
    ctx.save(); ctx.lineCap = "round"; ctx.lineJoin = "round";
    if (edge.type === "flyover") {
      ctx.shadowColor = "rgba(0,0,0,.55)"; ctx.shadowBlur = 7; ctx.shadowOffsetY = 4;
      ctx.strokeStyle = "#3f6069"; ctx.lineWidth = widthPx;
    } else if (edge.type === "ramp") {
      ctx.strokeStyle = "#57686a"; ctx.lineWidth = widthPx;
    } else {
      ctx.strokeStyle = "#34464a"; ctx.lineWidth = widthPx;
    }
    ctx.stroke(); ctx.restore();
    if (edge.type === "flyover") {
      strokeRoadPath(ctx, edge.polyline, transform); ctx.save(); ctx.strokeStyle = "rgba(177,214,220,.3)"; ctx.lineWidth = 1; ctx.stroke(); ctx.restore();
      // Low piers visually separate the raised deck from the arterial beneath it.
      const middle = edge.polyline[Math.floor(edge.polyline.length / 2)];
      const foot = transform(middle[0], middle[1] - Math.sign(middle[1] || 1) * 28), top = transform(middle[0], middle[1]);
      ctx.save(); ctx.strokeStyle = "#45575a"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(top[0], top[1]); ctx.lineTo(foot[0], foot[1]); ctx.stroke(); ctx.restore();
    }
    drawRoadMarkings(ctx, edge, transform);
  };

  for (const edge of network.edges.filter((item) => item.type === "road")) drawEdge(edge);
  for (const edge of network.edges.filter((item) => item.type === "ramp")) drawEdge(edge);
  for (const edge of network.edges.filter((item) => item.type === "flyover")) drawEdge(edge);

  for (const node of network.nodes) {
    const [x, y] = transform(node.x, node.y);
    ctx.beginPath(); ctx.arc(x, y, node.type === "signalized" ? 9 : 5, 0, Math.PI * 2);
    ctx.fillStyle = node.type === "signalized" ? "#283638" : node.type === "merge" ? "#354446" : "#506261"; ctx.fill();
    if (node.type === "signalized") { ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fillStyle = "#e8b45f"; ctx.fill(); }
    if (node.type !== "merge") {
      ctx.font = "600 10px system-ui, sans-serif"; const textWidth = ctx.measureText(node.id).width;
      ctx.fillStyle = "rgba(11,18,19,.82)"; ctx.beginPath(); ctx.roundRect(x + 8, y - 18, textWidth + 10, 16, 5); ctx.fill();
      ctx.fillStyle = "#d4dfd9"; ctx.fillText(node.id, x + 13, y - 7);
    }
  }
  drawStreetlights(ctx, network, transform);
}

function drawSignal(ctx: CanvasRenderingContext2D, node: Network["nodes"][number], transform: Transform, timeS: number, greenS: number, signal: typeof SIGNALS[number]) {
  const phaseTime = (timeS + signal.offset) % signal.cycle;
  const active = phaseTime < greenS ? "green" : phaseTime < greenS + signal.yellow ? "yellow" : "red";
  const [nodeX, nodeY] = transform(node.x, node.y);
  const x = nodeX + 18, y = nodeY - 17;
  ctx.save(); ctx.fillStyle = "#101719"; ctx.strokeStyle = "#6b7b78"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.roundRect(x - 5, y - 13, 10, 28, 4); ctx.fill(); ctx.stroke();
  const lamps = [{ state: "red", color: "#ef6657", y: -7 }, { state: "yellow", color: "#f3c44e", y: 1 }, { state: "green", color: "#4fce8c", y: 9 }];
  for (const lamp of lamps) {
    const lit = active === lamp.state;
    ctx.save(); ctx.globalAlpha = lit ? 1 : 0.2;
    if (lit) { ctx.shadowColor = lamp.color; ctx.shadowBlur = 4; }
    ctx.fillStyle = lamp.color; ctx.beginPath(); ctx.arc(x, y + lamp.y, 2.2, 0, Math.PI * 2); ctx.fill(); ctx.restore();
  }
  ctx.restore();
}

function drawCar(ctx: CanvasRenderingContext2D, x: number, y: number, angle: number, color: string, alpha: number) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(angle); ctx.globalAlpha = alpha;
  ctx.shadowColor = "rgba(0,0,0,.3)"; ctx.shadowBlur = 2; ctx.shadowOffsetY = 1;
  ctx.fillStyle = color; ctx.beginPath(); ctx.roundRect(-8, -4, 16, 8, 2.3); ctx.fill();
  ctx.shadowColor = "transparent"; ctx.shadowBlur = 0;
  ctx.fillStyle = "rgba(13,25,29,.66)"; ctx.beginPath(); ctx.roundRect(-2.5, -2.9, 5.2, 5.8, 1.2); ctx.fill();
  ctx.fillStyle = "#fff0bc";
  ctx.beginPath(); ctx.arc(6.4, -2.3, 0.8, 0, Math.PI * 2); ctx.arc(6.4, 2.3, 0.8, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#df564c";
  ctx.beginPath(); ctx.arc(-6.6, -2.3, 0.8, 0, Math.PI * 2); ctx.arc(-6.6, 2.3, 0.8, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
}

export function CanvasPlayer({ network, frames, signalGreenS }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const staticCanvasRef = useRef<HTMLCanvasElement>(null);
  const transformRef = useRef<Transform | null>(null);
  const drawRef = useRef<((timeS: number) => void) | null>(null);
  const playheadRef = useRef(0);
  const performanceMarkRef = useRef<{ timestamp: number; frameMs: number; vehicles: number }[]>([]);
  const lastReadoutRef = useRef(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [playhead, setPlayhead] = useState(0);
  const [perf, setPerf] = useState<PerfReadout>({ fps: 0, renderMs: 0, vehicles: 0 });
  const times = useMemo(() => [...new Set(frames.t)].sort((a, b) => a - b), [frames.t]);
  const edgeById = useMemo(() => new Map(network.edges.map((edge) => [edge.id, edge])), [network.edges]);
  const geometryById = useMemo(() => buildGeometry(network), [network]);
  const framesByTime = useMemo(() => {
    const result = new Map<number, Map<number, VehicleFrame>>();
    for (let index = 0; index < frames.t.length; index++) {
      let frame = result.get(frames.t[index]);
      if (!frame) { frame = new Map<number, VehicleFrame>(); result.set(frames.t[index], frame); }
      frame.set(frames.id[index], { edge: frames.edge[index], s: frames.s[index], lane: frames.lane[index], v: frames.v[index] });
    }
    return result;
  }, [frames]);
  const frameIndex = (time: number) => {
    let low = 0, high = times.length;
    while (low < high) { const mid = (low + high) >>> 1; if (times[mid] <= time) low = mid + 1; else high = mid; }
    return Math.max(0, Math.min(times.length - 1, low - 1));
  };
  const timeIndex = frameIndex(playhead);

  useEffect(() => { playheadRef.current = playhead; drawRef.current?.(playhead); }, [playhead]);

  useEffect(() => {
    const canvas = canvasRef.current, staticCanvas = staticCanvasRef.current;
    if (!canvas || !staticCanvas) return;
    const rebuildStatic = () => {
      const width = canvas.clientWidth, height = canvas.clientHeight, dpr = Math.max(1, window.devicePixelRatio || 1);
      if (!width || !height) return;
      canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
      staticCanvas.width = canvas.width; staticCanvas.height = canvas.height;
      const staticCtx = staticCanvas.getContext("2d");
      const visibleCtx = canvas.getContext("2d");
      if (!staticCtx || !visibleCtx) return;
      staticCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
      visibleCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const transform = worldTransform(network, width, height);
      transformRef.current = transform;
      drawStaticLayer(staticCtx, network, transform, width, height);
    };
    rebuildStatic();
    const observer = new ResizeObserver(rebuildStatic); observer.observe(canvas);

    const draw = (timeS: number) => {
      const started = performance.now(), visibleCtx = canvas.getContext("2d"), buffer = staticCanvasRef.current;
      const transform = transformRef.current;
      if (!visibleCtx || !buffer || !transform) return;
      const width = canvas.clientWidth, height = canvas.clientHeight, dpr = Math.max(1, window.devicePixelRatio || 1);
      visibleCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
      visibleCtx.clearRect(0, 0, width, height);
      visibleCtx.drawImage(buffer, 0, 0, width, height);
      let vehicleCount = 0;

      for (const signal of SIGNALS) {
        const node = network.nodes.find((item) => item.id === signal.node);
        if (node) drawSignal(visibleCtx, node, transform, timeS, signalGreenS, signal);
      }
      if (times.length) {
        const leftIndex = frameIndex(timeS), leftTime = times[leftIndex], rightTime = times[Math.min(leftIndex + 1, times.length - 1)];
        const alpha = rightTime === leftTime ? 0 : Math.max(0, Math.min(1, (timeS - leftTime) / (rightTime - leftTime)));
        const left = framesByTime.get(leftTime) ?? new Map<number, VehicleFrame>();
        const right = framesByTime.get(rightTime) ?? left;
        const ids = new Set([...left.keys(), ...right.keys()]);
        for (const id of ids) {
          const a = left.get(id), b = right.get(id);
          const chosen = a && b ? a.edge === b.edge
            ? { ...a, s: a.s + (b.s - a.s) * alpha, lane: alpha < 0.5 ? a.lane : b.lane, v: a.v + (b.v - a.v) * alpha }
            : (alpha < 0.5 ? a : b)
            : (alpha < 0.5 ? a : b);
          if (!chosen) continue;
          const edge = edgeById.get(chosen.edge), geometry = geometryById.get(chosen.edge);
          if (!edge || !geometry) continue;
          const point = pointAt(edge, geometry, chosen.s, chosen.lane), [x, y] = transform(point.x, point.y);
          const paletteIndex = Math.abs(Math.imul(id ^ 0x45d9f3b, 0x45d9f3b)) % CAR_PALETTE.length;
          drawCar(visibleCtx, x, y, point.angle, CAR_PALETTE[paletteIndex], 1);
          vehicleCount++;
        }
      }
      const ended = performance.now();
      performanceMarkRef.current.push({ timestamp: performance.now(), frameMs: ended - started, vehicles: vehicleCount });
      const now = performance.now();
      if (now - lastReadoutRef.current >= 750) {
        const recent = performanceMarkRef.current.filter((sample) => now - sample.timestamp <= 2000);
        if (recent.length > 1) {
          const elapsed = recent[recent.length - 1].timestamp - recent[0].timestamp;
          const fps = elapsed > 0 ? (recent.length - 1) * 1000 / elapsed : 0;
          setPerf({ fps, renderMs: recent.reduce((sum, sample) => sum + sample.frameMs, 0) / recent.length, vehicles: recent[recent.length - 1].vehicles });
        }
        performanceMarkRef.current = recent; lastReadoutRef.current = now;
      }
    };
    drawRef.current = draw;
    draw(playheadRef.current);
    return () => { observer.disconnect(); drawRef.current = null; };
  }, [edgeById, framesByTime, geometryById, network, signalGreenS, times]);

  useEffect(() => {
    if (!playing || times.length < 2) return;
    let previous = 0, lastUi = 0, raf = 0;
    const end = times[times.length - 1] || 0;
    const tick = (now: number) => {
      if (previous) {
        playheadRef.current = end > 0 ? (playheadRef.current + (now - previous) / 1000 * speed) % end : 0;
        drawRef.current?.(playheadRef.current);
        if (now - lastUi > 120) { setPlayhead(playheadRef.current); lastUi = now; }
      }
      previous = now; raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, times]);

  const onSeek = useCallback((index: number) => {
    setPlaying(false); playheadRef.current = times[index] ?? 0; setPlayhead(playheadRef.current); drawRef.current?.(playheadRef.current);
  }, [times]);

  return <section className="player card">
    <canvas ref={canvasRef} className="traffic-canvas" aria-label="Animated traffic simulation" />
    <canvas ref={staticCanvasRef} className="traffic-static-buffer" aria-hidden="true" />
    <div className="player-controls">
      <button className="button secondary" onClick={() => setPlaying((value) => !value)}>{playing ? "Pause" : "Play"}</button>
      <label>Speed <select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option></select></label>
      <input aria-label="Timeline" type="range" min={0} max={Math.max(0, times.length - 1)} value={timeIndex} onChange={(event) => onSeek(Number(event.target.value))} />
      <span className="mono">{playhead.toFixed(1)} s</span>
      <output className="render-stats" aria-label="Canvas rendering performance">{perf.fps ? `${perf.fps.toFixed(0)} FPS · ${perf.renderMs.toFixed(2)} ms · ${perf.vehicles} cars` : "FPS —"}</output>
    </div>
  </section>;
}

