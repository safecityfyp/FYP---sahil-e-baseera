import { useMemo } from 'react'
import { Download, Calendar } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import { SEVERITY_META } from '../../constants'
import { filterByRange, rangeFor, formatRangeLabel } from '../../lib/reportPeriod'
import type { ReportPeriod } from '../../types'

const PERIOD_OPTIONS: Array<{ id: ReportPeriod; label: string }> = [
  { id: 'today', label: 'Today' },
  { id: 'week', label: 'This Week' },
  { id: 'month', label: 'This Month' },
  { id: 'year', label: 'This Year' },
  { id: 'all', label: 'All Time' },
]

export default function IncidentLog() {
  const { incidents, canEdit, now, reportPeriod, setReportPeriod, customRange } = useApp()

  // ---- same period filter used by Analytics + PDF (Fix 2) ----
  const range = useMemo(
    () => rangeFor(reportPeriod, now, customRange ?? undefined),
    [reportPeriod, now, customRange],
  )
  const filtered = useMemo(() => filterByRange(incidents, range), [incidents, range])
  const rangeLabel = formatRangeLabel(range)

  const highCount = filtered.filter((i) => i.severity === 'high').length
  const mediumCount = filtered.filter((i) => i.severity === 'medium').length
  const lowCount = filtered.filter((i) => i.severity === 'low').length

  const downloadCSV = () => {
    const headers = [
      'Timestamp',
      'Camera',
      'Zone',
      'Event',
      'Severity',
      'Confidence',
      'Plate',
      'Vehicle',
      'Speed',
    ]
    const rows = filtered.map((i) => [
      i.clockLabel,
      `${i.cameraIndex} — ${i.cameraName}`,
      i.zone,
      i.event,
      i.severity.toUpperCase(),
      `${i.confidence}%`,
      i.plate ?? '—',
      i.vehicle ?? '—',
      i.speed ?? '—',
    ])
    const csv = [headers, ...rows].map((r) => r.map((c) => `"${c}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `incident-log-${new Date().toISOString().split('T')[0]}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 bg-base p-6 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="hud-label text-2xl text-gold-soft">INCIDENT LOG</h1>
          <span className="rounded border border-cyan/40 bg-cyan/10 px-2 py-0.5 text-[10px] font-bold text-cyan">
            DATA: PERSISTED INCIDENT LOG
          </span>
        </div>
        {canEdit && (
          <button onClick={downloadCSV} className="btn gap-2">
            <Download className="h-4 w-4" />
            Export CSV
          </button>
        )}
      </div>

      {/* Period filter — shared with Analytics / PDF */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-slate-400">REPORT PERIOD:</span>
        {PERIOD_OPTIONS.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setReportPeriod(id)}
            className={`btn text-xs ${reportPeriod === id ? 'border-gold/60 bg-gold/15 text-gold-soft' : ''}`}
          >
            {label}
          </button>
        ))}
        <div className="flex-1" />
        <span className="inline-flex items-center gap-1.5 text-[11px] font-mono text-cyan">
          <Calendar className="h-3.5 w-3.5" />
          {rangeLabel}
        </span>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Critical', count: highCount, color: 'danger' },
          { label: 'Warning', count: mediumCount, color: 'warn' },
          { label: 'Advisory', count: lowCount, color: 'info' },
        ].map(({ label, count, color }) => (
          <div key={label} className="rounded-lg border border-edge/50 bg-surface2/40 p-3">
            <div className="text-[11px] text-slate-400 mb-1">{label}</div>
            <div className={`text-2xl font-bold text-${color}`}>{count}</div>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto rounded-lg border border-edge/50 bg-surface2/30">
        <table className="w-full text-sm">
          <thead className="sticky top-0 border-b border-edge/50 bg-surface/80">
            <tr className="text-slate-300 text-[11px] font-semibold uppercase tracking-wider">
              <th className="px-3 py-2 text-left">Time</th>
              <th className="px-3 py-2 text-left">Camera</th>
              <th className="px-3 py-2 text-left">Event</th>
              <th className="px-3 py-2 text-left">Severity</th>
              <th className="px-3 py-2 text-left">Confidence</th>
              <th className="px-3 py-2 text-left">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-edge/30">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-slate-500">
                  No incidents recorded in this period ({rangeLabel})
                </td>
              </tr>
            ) : (
              filtered.map((inc) => {
                const sev = SEVERITY_META[inc.severity]
                return (
                  <tr key={inc.id} className="border-edge/20 even:bg-white/[0.02] hover:bg-steel/10 transition">
                    <td className="px-3 py-2 font-mono text-[10px] text-slate-400">
                      {inc.clockLabel}
                    </td>
                    <td className="px-3 py-2 text-slate-300">
                      <span className="text-gold-soft font-semibold">CAM {inc.cameraIndex}</span>
                      <br />
                      <span className="text-[10px] text-slate-500">{inc.zone}</span>
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-semibold text-slate-200">{inc.event}</div>
                      <div className="text-[10px] text-slate-400 mt-0.5">{inc.detail}</div>
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className="inline-block px-2 py-0.5 rounded text-[10px] font-bold"
                        style={{
                          backgroundColor: `${sev.color}30`,
                          color: sev.color,
                          borderColor: sev.color,
                          borderWidth: '1px',
                        }}
                      >
                        {sev.label}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-300">{inc.confidence}%</td>
                    <td className="px-3 py-2 text-[10px] text-slate-400 space-y-1">
                      {inc.plate && <div>Plate: {inc.plate}</div>}
                      {inc.vehicle && <div>{inc.vehicle}</div>}
                      {inc.speed && <div>Speed: {inc.speed} km/h</div>}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </main>
  )
}
