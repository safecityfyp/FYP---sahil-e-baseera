import { useMemo, useState } from 'react'
import { Search, MapPin, Route, Car, ScanLine } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import { SEVERITY_META } from '../../constants'
import ModelBadge from '../ui/ModelBadge'

/**
 * Forensic trajectory search — built entirely from the REAL persisted incident
 * store (no fabricated data). Query by license plate or vehicle description
 * returns the chronological route of matching detections across camera nodes.
 */
export default function TrajectorySearch() {
  const { incidents, openForensic } = useApp()
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')

  const results = useMemo(() => {
    const q = submitted.trim().toUpperCase()
    if (q.length < 2) return []
    return incidents
      .filter((inc) => {
        const plate = (inc.plate ?? '').toUpperCase()
        const vehicle = (inc.vehicle ?? '').toUpperCase()
        return plate.includes(q) || vehicle.includes(q)
      })
      .sort((a, b) => a.firedAt - b.firedAt)
  }, [incidents, submitted])

  // distinct cameras crossed by the matched vehicle in the matched order
  const route = useMemo(() => {
    const seen = new Set<string>()
    const nodes: typeof results = []
    results.forEach((inc) => {
      if (!seen.has(inc.cameraId)) {
        seen.add(inc.cameraId)
        nodes.push(inc)
      }
    })
    return nodes
  }, [results])

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto bg-base p-6">
      <div className="flex items-center gap-3">
        <h1 className="hud-label text-2xl text-gold-soft">FORENSIC TRAJECTORY SEARCH</h1>
        <span className="rounded border border-cyan/40 bg-cyan/10 px-2 py-0.5 text-[10px] font-bold text-cyan">
          DATA: PERSISTED INCIDENT LOG
        </span>
      </div>

      {/* Search box */}
      <div className="rounded-lg border border-edge/50 bg-surface2/40 p-4">
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && setSubmitted(query)}
              placeholder="Query by plate (e.g. RWP-9918) or vehicle (e.g. Honda, Corolla, CD-70)…"
              className="w-full rounded-lg border border-edge2/50 bg-surface/60 py-2 pl-9 pr-3 text-sm text-slate-200 placeholder:text-slate-500 focus:border-cyan/60 focus:outline-none"
            />
          </div>
          <button onClick={() => setSubmitted(query)} className="btn-gold text-xs px-4">
            <Route className="h-4 w-4" />
            Search
          </button>
        </div>
        <p className="mt-2 text-[10px] text-slate-500">
          Tip: sample plates in the log — RWP-9918, RWP-2231, JW-4451, LEB-4471, RIY-1188
        </p>
      </div>

      {submitted && results.length === 0 && (
        <div className="rounded-lg border border-edge/50 bg-surface2/30 p-8 text-center">
          <Car className="mx-auto mb-2 h-8 w-8 text-slate-500" />
          <div className="text-sm font-semibold text-slate-300">No matches for “{submitted}”</div>
          <div className="mt-1 text-xs text-slate-500">
            Run a live demo session first so incidents populate the persisted log.
          </div>
        </div>
      )}

      {results.length > 0 && (
        <>
          {/* Route visualization */}
          <div className="rounded-lg border border-edge/50 bg-surface2/30 p-4">
            <h2 className="hud-label mb-3 text-sm text-gold-soft">
              TRAJECTORY — {results[0].plate ?? results[0].vehicle ?? 'unknown'} ({results.length} detections)
            </h2>
            <div className="flex flex-wrap items-center gap-2">
              {route.map((inc, idx) => (
                <div key={inc.id} className="flex items-center gap-2">
                  <button
                    onClick={() => openForensic(inc.cameraId)}
                    className="fade-up rounded-lg border border-cyan/40 bg-cyan/10 px-3 py-2 text-left transition hover:bg-cyan/20"
                    style={{ animationDelay: `${idx * 80}ms` }}
                    title="Open forensic playback for this camera"
                  >
                    <div className="flex items-center gap-2">
                      <MapPin className="h-3.5 w-3.5 text-cyan" />
                      <span className="text-xs font-bold text-cyan">CAM {inc.cameraIndex}</span>
                    </div>
                    <div className="mt-0.5 text-[10px] text-slate-400">
                      {inc.zone} · {new Date(inc.firedAt).toLocaleTimeString('en-GB', { hour12: false })}
                    </div>
                  </button>
                  {idx < route.length - 1 && (
                    <span className="h-px w-6 border-t border-dashed border-cyan/40" />
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Chronological detection list */}
          <div className="rounded-lg border border-edge/50 bg-surface2/30">
            <div className="hud-label border-b border-edge/50 px-4 py-2 text-[10px] text-slate-400">
              CHRONOLOGICAL DETECTIONS
            </div>
            <div className="max-h-[40vh] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 border-b border-edge/50 bg-surface/80">
                  <tr className="text-slate-300 text-[10px] font-semibold uppercase tracking-wider">
                    <th className="px-3 py-2 text-left">Time</th>
                    <th className="px-3 py-2 text-left">Camera</th>
                    <th className="px-3 py-2 text-left">Event</th>
                    <th className="px-3 py-2 text-left">Plate</th>
                    <th className="px-3 py-2 text-left">Vehicle</th>
                    <th className="px-3 py-2 text-left">Severity</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-edge/30">
                  {results.map((inc) => (
                    <tr key={inc.id} className="even:bg-white/[0.02] hover:bg-steel/10 transition">
                      <td className="px-3 py-2 font-mono text-[10px] text-slate-400">
                        {new Date(inc.firedAt).toLocaleString('en-GB', { hour12: false })}
                      </td>
                      <td className="px-3 py-2 text-gold-soft font-semibold">CAM {inc.cameraIndex}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="text-slate-300">{inc.event}</span>
                          <ModelBadge id={inc.modelId} size="xs" />
                        </div>
                      </td>
                      <td className="px-3 py-2 font-mono text-[10px] text-cyan">{inc.plate ?? '—'}</td>
                      <td className="px-3 py-2 text-slate-300">{inc.vehicle ?? '—'}</td>
                      <td className="px-3 py-2">
                        <span
                          className="rounded px-1.5 py-0.5 text-[9px] font-bold"
                          style={{
                            color: SEVERITY_META[inc.severity].color,
                            backgroundColor: `${SEVERITY_META[inc.severity].color}18`,
                            border: `1px solid ${SEVERITY_META[inc.severity].color}55`,
                          }}
                        >
                          {SEVERITY_META[inc.severity].label}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {!submitted && (
        <div className="rounded-lg border border-edge/50 bg-surface2/30 p-8 text-center">
          <ScanLine className="mx-auto mb-2 h-8 w-8 text-slate-500" />
          <div className="text-sm font-semibold text-slate-300">Trajectory reconstruction</div>
          <div className="mt-1 text-xs text-slate-500">
            Search the persisted incident log by plate or vehicle to trace a route across camera nodes.
          </div>
        </div>
      )}
    </main>
  )
}
