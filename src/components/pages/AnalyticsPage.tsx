import { useMemo, useState } from 'react'
import { Download, Mail, Calendar, X, Send } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import { SEVERITY_META, AI_MODELS } from '../../constants'
import { filterByRange, rangeFor, formatRangeLabel, startOfDay } from '../../lib/reportPeriod'
import { buildSeedIncidents } from '../../lib/seedAnalytics'
import type { ReportPeriod } from '../../types'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'

const PERIOD_OPTIONS: Array<{ id: ReportPeriod; label: string }> = [
  { id: 'today', label: 'Today' },
  { id: 'week', label: 'This Week' },
  { id: 'month', label: 'This Month' },
  { id: 'year', label: 'This Year' },
  { id: 'all', label: 'All Time' },
]

/** Shared empty-state panel shown when the selected period has no incidents. */
function EmptyPeriod({ rangeLabel }: { rangeLabel: string }) {
  return (
    <div className="col-span-2 rounded-lg border border-edge/50 bg-surface2/30 p-8 text-center">
      <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full border border-edge2/50 bg-surface/60 text-slate-500">
        <Calendar className="h-5 w-5" />
      </div>
      <div className="text-sm font-semibold text-slate-300">No incidents recorded in this period</div>
      <div className="mt-1 text-xs text-slate-500">{rangeLabel}</div>
    </div>
  )
}

/** Build the timeline buckets appropriate for the selected period span. */
function timelineFor(
  filtered: Array<{ firedAt: number }>,
  range: { start: number; end: number },
): Array<{ time: string; events: number }> {
  const spanMs = range.end - range.start
  // < 2 days → hourly; < 45 days → daily; else monthly
  if (spanMs < 2 * 24 * 3600_000) {
    return Array.from({ length: 24 }, (_, i) => ({
      time: `${String(i).padStart(2, '0')}:00`,
      events: filtered.filter((inc) => new Date(inc.firedAt).getHours() === i).length,
    }))
  }
  if (spanMs < 45 * 24 * 3600_000) {
    const days = Math.min(40, Math.max(2, Math.round(spanMs / (24 * 3600_000))))
    return Array.from({ length: days }, (_, i) => {
      const dayStart = range.end - (days - i) * 24 * 3600_000
      const dayEnd = dayStart + 24 * 3600_000
      return {
        time: new Date(dayStart).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }),
        events: filtered.filter((inc) => inc.firedAt >= dayStart && inc.firedAt < dayEnd).length,
      }
    })
  }
  // monthly
  const buckets: Array<{ time: string; events: number }> = []
  const startYear = new Date(range.start).getFullYear()
  const endYear = new Date(Math.min(range.end - 1, Date.now())).getFullYear()
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  for (let y = startYear; y <= endYear; y++) {
    const mStart = y === startYear ? new Date(range.start).getMonth() : 0
    const mEnd = y === endYear ? new Date(Math.min(range.end - 1, Date.now())).getMonth() : 11
    for (let m = mStart; m <= mEnd; m++) {
      const from = new Date(y, m, 1).getTime()
      const to = new Date(y, m + 1, 1).getTime()
      buckets.push({
        time: `${months[m]} ${String(y).slice(2)}`,
        events: filtered.filter((inc) => inc.firedAt >= from && inc.firedAt < to).length,
      })
    }
  }
  return buckets
}

export default function AnalyticsPage() {
  const { incidents, cameras, now, canEdit, reportPeriod, setReportPeriod, customRange, setCustomRange } =
    useApp()

  // ---- period filtering (Fix 2) ----
  const range = useMemo(
    () => rangeFor(reportPeriod, now, customRange ?? undefined),
    [reportPeriod, now, customRange],
  )
  const rangeLabel = formatRangeLabel(range)

  // ---- warehouse dataset: seeded historical + live session (item 1) ----
  // Regenerate the seed history once per day (anchored to start-of-day) so it
  // is deterministic and cheap while `now` ticks every second.
  const dayAnchor = startOfDay(new Date(now))
  const seedIncidents = useMemo(
    () => buildSeedIncidents(dayAnchor, cameras),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dayAnchor, cameras],
  )
  const warehouse = useMemo(() => {
    const seen = new Set<string>()
    const merged: typeof incidents = []
    // Seed first (they are the older history), then live on top.
    for (const inc of [...seedIncidents, ...incidents]) {
      if (seen.has(inc.id)) continue
      seen.add(inc.id)
      merged.push(inc)
    }
    return merged.sort((a, b) => b.firedAt - a.firedAt)
  }, [seedIncidents, incidents])

  const filtered = useMemo(() => filterByRange(warehouse, range), [warehouse, range])

  const [emailOpen, setEmailOpen] = useState(false)
  const [emailTo, setEmailTo] = useState('')
  const [emailSent, setEmailSent] = useState(false)
  const [customFrom, setCustomFrom] = useState(() => {
    const d = new Date(customRange?.from ?? Date.now() - 7 * 24 * 3600_000)
    return d.toISOString().slice(0, 10)
  })
  const [customTo, setCustomTo] = useState(() => {
    const d = new Date(customRange?.to ?? Date.now())
    return d.toISOString().slice(0, 10)
  })

  // ---- summary (from filtered set, never the whole history) ----
  const totalIncidents = filtered.length
  const highCount = filtered.filter((i) => i.severity === 'high').length
  const mediumCount = filtered.filter((i) => i.severity === 'medium').length
  const lowCount = filtered.filter((i) => i.severity === 'low').length

  // ---- charts from the SAME filtered event log ----
  const modelChartData = useMemo(() => {
    const counts: Record<string, number> = {}
    AI_MODELS.forEach((m) => (counts[m.id] = 0))
    filtered.forEach((inc) => {
      if (counts[inc.modelId] !== undefined) counts[inc.modelId]++
    })
    return AI_MODELS.map((m) => ({ name: m.short, value: counts[m.id] })).filter((d) => d.value > 0)
  }, [filtered])

  const severityData = useMemo(
    () =>
      [
        { name: 'Critical', value: highCount, fill: '#EF4444' },
        { name: 'Warning', value: mediumCount, fill: '#F59E0B' },
        { name: 'Advisory', value: lowCount, fill: '#3B82F6' },
      ].filter((d) => d.value > 0),
    [highCount, mediumCount, lowCount],
  )

  const cameraChartData = useMemo(() => {
    const counts: Record<number, number> = {}
    filtered.forEach((inc) => {
      counts[inc.cameraIndex] = (counts[inc.cameraIndex] ?? 0) + 1
    })
    return Object.entries(counts)
      .map(([idx, count]) => ({ cam: `CAM ${idx}`, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8)
  }, [filtered])

  const timelineData = useMemo(() => timelineFor(filtered, range), [filtered, range])

  const heatmap = useMemo(() => {
    const grid: Array<{ day: string; hours: number[] }> = []
    for (let d = 0; d < 7; d++) {
      grid.push({ day: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d], hours: Array(24).fill(0) })
    }
    filtered.forEach((inc) => {
      const dt = new Date(inc.firedAt)
      grid[dt.getDay()].hours[dt.getHours()]++
    })
    return grid
  }, [filtered])
  const heatMax = Math.max(1, ...heatmap.flatMap((d) => d.hours))

  // ---- PDF export (item 3: high-contrast, readable) ----
  const generatePDF = () => {
    const doc = new jsPDF()
    const pageWidth = doc.internal.pageSize.getWidth()

    // Dark text on white — maximum legibility when printed or viewed.
    const INK: [number, number, number] = [15, 23, 42] // near-black navy
    const GRAY: [number, number, number] = [71, 85, 105] // slate-600 body text
    const ACCENT: [number, number, number] = [139, 108, 25] // deep gold (legible on white)

    // Header — white page, dark title
    doc.setFillColor(15, 23, 42)
    doc.rect(0, 0, pageWidth, 40, 'F')
    doc.setTextColor(255, 255, 255)
    doc.setFontSize(16)
    doc.text('PNS SafeCity — Incident Report', pageWidth / 2, 18, { align: 'center' })
    doc.setFontSize(10)
    doc.setTextColor(226, 232, 240)
    doc.text(`Generated: ${new Date(now).toLocaleString('en-GB')}`, pageWidth / 2, 25, {
      align: 'center',
    })
    doc.setFontSize(11)
    doc.setTextColor(201, 162, 39)
    doc.text(`Report Period: ${rangeLabel}`, pageWidth / 2, 33, { align: 'center' })

    // Summary — dark text on light table
    let yPos = 52
    doc.setFontSize(12)
    doc.setTextColor(...ACCENT)
    doc.text('SUMMARY', 20, yPos)
    yPos += 8
    autoTable(doc, {
      startY: yPos,
      head: [['Metric', 'Count']],
      body: [
        ['Total Incidents', String(totalIncidents)],
        ['Critical Alerts', String(highCount)],
        ['Warnings', String(mediumCount)],
        ['Advisory', String(lowCount)],
      ],
      theme: 'grid',
      styles: { fillColor: [255, 255, 255], textColor: INK, lineColor: [203, 213, 225] },
      headStyles: { fillColor: [15, 23, 42], textColor: [255, 255, 255] },
      alternateRowStyles: { fillColor: [248, 250, 252] },
      margin: { left: 20, right: 20 },
    })
    yPos = (doc as any).lastAutoTable.finalY + 14

    if (filtered.length === 0) {
      doc.setFontSize(12)
      doc.setTextColor(...GRAY)
      doc.text('No incidents recorded for the selected period.', 20, yPos)
      doc.save(`safecity-report-${new Date().toISOString().split('T')[0]}.pdf`)
      return
    }

    // Incidents — dark text on light striped table, paginated by autotable
    doc.setFontSize(12)
    doc.setTextColor(...ACCENT)
    doc.text('INCIDENTS', 20, yPos)
    yPos += 8
    const tableData = filtered.map((inc) => [
      new Date(inc.firedAt).toLocaleString('en-GB', { hour12: false }),
      `CAM ${inc.cameraIndex} — ${inc.cameraName}`,
      inc.zone,
      inc.event,
      SEVERITY_META[inc.severity].label,
      `${inc.confidence}%`,
    ])
    autoTable(doc, {
      startY: yPos,
      head: [['Time', 'Camera', 'Zone', 'Event', 'Severity', 'Confidence']],
      body: tableData,
      theme: 'grid',
      styles: { fontSize: 8, textColor: INK, cellPadding: 2, lineColor: [203, 213, 225] },
      headStyles: { fillColor: [15, 23, 42], textColor: [255, 255, 255] },
      alternateRowStyles: { fillColor: [248, 250, 252] },
      margin: { left: 20, right: 20 },
    })

    doc.save(`safecity-report-${new Date().toISOString().split('T')[0]}.pdf`)
  }

  const sendEmail = () => {
    const payload = {
      to: emailTo,
      subject: `PNS SafeCity Report — ${rangeLabel}`,
      period: rangeLabel,
      summary: { total: totalIncidents, high: highCount, medium: mediumCount, low: lowCount },
      incidents: filtered.map((i) => ({ time: i.clockLabel, cam: i.cameraId, event: i.event, severity: i.severity })),
      at: new Date().toISOString(),
    }
    console.log('[DEMO MODE] Mock email payload:', payload)
    setEmailSent(true)
    window.setTimeout(() => {
      setEmailOpen(false)
      setEmailSent(false)
      setEmailTo('')
    }, 1400)
  }

  const applyCustomRange = () => {
    const from = new Date(`${customFrom}T00:00:00`).getTime()
    const to = new Date(`${customTo}T23:59:59`).getTime()
    if (!Number.isNaN(from) && !Number.isNaN(to) && from <= to) {
      setCustomRange({ from, to })
      setReportPeriod('custom')
    }
  }

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto bg-base p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="hud-label text-2xl text-gold-soft">ANALYTICS & REPORTING</h1>
          <span className="rounded border border-cyan/40 bg-cyan/10 px-2 py-0.5 text-[10px] font-bold text-cyan">
            DATA: INCIDENT LOG + SEED HISTORY
          </span>
        </div>
        {canEdit && (
          <div className="flex items-center gap-2">
            <button onClick={generatePDF} className="btn gap-2">
              <Download className="h-4 w-4" />
              PDF Report
            </button>
            <button onClick={() => setEmailOpen(true)} className="btn gap-2">
              <Mail className="h-4 w-4" />
              Email
            </button>
          </div>
        )}
      </div>

      {/* Period selector */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-edge/50 bg-surface2/40 px-4 py-3">
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
        <div className="mx-1 h-6 w-px bg-edge2/50" />
        <input
          type="date"
          value={customFrom}
          onChange={(e) => setCustomFrom(e.target.value)}
          className="btn text-xs"
          title="Custom range start"
        />
        <span className="text-xs text-slate-500">→</span>
        <input
          type="date"
          value={customTo}
          onChange={(e) => setCustomTo(e.target.value)}
          className="btn text-xs"
          title="Custom range end"
        />
        <button onClick={applyCustomRange} className="btn text-xs gap-2" title="Apply custom range">
          <Calendar className="h-3.5 w-3.5" />
          Apply
        </button>
        <div className="flex-1" />
        <span className="text-[11px] text-cyan font-mono">{rangeLabel}</span>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: 'Total Events', value: totalIncidents, color: 'text-cyan' },
          { label: 'Critical', value: highCount, color: 'text-danger' },
          { label: 'Warnings', value: mediumCount, color: 'text-warn' },
          { label: 'Advisory', value: lowCount, color: 'text-info' },
        ].map(({ label, value, color }) => (
          <div key={label} className="rounded-lg border border-edge/50 bg-surface2/50 p-4 text-center">
            <div className={`text-3xl font-bold ${color}`}>{value}</div>
            <div className="text-xs text-slate-400 mt-1">{label}</div>
          </div>
        ))}
      </div>

      {/* Charts grid */}
      {filtered.length === 0 ? (
        <EmptyPeriod rangeLabel={rangeLabel} />
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {modelChartData.length > 0 && (
            <div className="rounded-lg border border-edge/50 bg-surface2/30 p-4">
              <h3 className="hud-label text-sm text-gold-soft mb-3">EVENTS BY MODEL</h3>
              <ResponsiveContainer width="100%" height={230}>
                <BarChart data={modelChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#293B52" />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#94a3b8' }} interval={0} />
                  <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} />
                  <Tooltip contentStyle={{ backgroundColor: '#17263A', border: '1px solid #293B52', color: '#F1F5F9' }} />
                  <Bar dataKey="value" fill="#16B8D4" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {severityData.length > 0 && (
            <div className="rounded-lg border border-edge/50 bg-surface2/30 p-4">
              <h3 className="hud-label text-sm text-gold-soft mb-3">SEVERITY DISTRIBUTION</h3>
              <ResponsiveContainer width="100%" height={230}>
                <PieChart>
                  <Pie data={severityData} dataKey="value" cx="50%" cy="50%" outerRadius={80}>
                    {severityData.map((entry, idx) => (
                      <Cell key={`cell-${idx}`} fill={entry.fill} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ backgroundColor: '#17263A', border: '1px solid #293B52', color: '#F1F5F9' }} />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="rounded-lg border border-edge/50 bg-surface2/30 p-4">
            <h3 className="hud-label text-sm text-gold-soft mb-3">HIGH-RISK ZONES (BY CAMERA)</h3>
            {cameraChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={230}>
                <BarChart data={cameraChartData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#293B52" />
                  <XAxis type="number" tick={{ fontSize: 11, fill: '#94a3b8' }} />
                  <YAxis dataKey="cam" type="category" tick={{ fontSize: 11, fill: '#94a3b8' }} width={56} />
                  <Tooltip contentStyle={{ backgroundColor: '#17263A', border: '1px solid #293B52', color: '#F1F5F9' }} />
                  <Bar dataKey="count" fill="#F59E0B" radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-[230px] items-center justify-center text-xs text-slate-500">
                No incidents recorded in this period
              </div>
            )}
          </div>

          <div className="rounded-lg border border-edge/50 bg-surface2/30 p-4">
            <h3 className="hud-label text-sm text-gold-soft mb-3">VIOLATION TREND</h3>
            <ResponsiveContainer width="100%" height={230}>
              <LineChart data={timelineData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#293B52" />
                <XAxis
                  dataKey="time"
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  interval={timelineData.length > 31 ? 'preserveStartEnd' : 0}
                />
                <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} />
                <Tooltip contentStyle={{ backgroundColor: '#17263A', border: '1px solid #293B52', color: '#F1F5F9' }} />
                <Line type="monotone" dataKey="events" stroke="#16B8D4" strokeWidth={2} dot={{ r: 2 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Peak-time heatmap */}
          <div className="col-span-2 rounded-lg border border-edge/50 bg-surface2/30 p-4">
            <h3 className="hud-label text-sm text-gold-soft mb-3">PEAK-TIME HEATMAP (HOUR × DAY)</h3>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] border-collapse text-center">
                <thead>
                  <tr>
                    <th className="p-1 text-[9px] text-slate-500">DAY</th>
                    {Array.from({ length: 24 }, (_, h) => (
                      <th key={h} className="p-1 text-[8px] text-slate-500">
                        {String(h).padStart(2, '0')}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {heatmap.map((row) => (
                    <tr key={row.day}>
                      <td className="p-1 text-[9px] font-bold text-gold-soft">{row.day}</td>
                      {row.hours.map((count, h) => {
                        const intensity = count === 0 ? 0 : 0.25 + (count / heatMax) * 0.75
                        const color =
                          count === 0
                            ? 'rgba(17,29,46,0.6)'
                            : count === 1
                              ? '#0E7490'
                              : count >= 3
                                ? '#EF4444'
                                : '#F59E0B'
                        return (
                          <td
                            key={h}
                            className="h-5 w-6 rounded-sm border border-edge/20"
                            style={{
                              backgroundColor: count === 0 ? 'rgba(17,29,46,0.6)' : color,
                              opacity: count === 0 ? 1 : 0.35 + intensity * 0.65,
                            }}
                            title={`${row.day} ${String(h).padStart(2, '0')}:00 — ${count} incident(s)`}
                          />
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Recent incidents table (filtered) */}
      <div className="rounded-lg border border-edge/50 bg-surface2/30 p-4">
        <h3 className="hud-label text-sm text-gold-soft mb-3">INCIDENT LOG — {rangeLabel.toUpperCase()}</h3>
        {filtered.length === 0 ? (
          <div className="py-6 text-center text-xs text-slate-500">
            No incidents recorded in this period
          </div>
        ) : (
          <div className="overflow-auto max-h-56">
            <table className="w-full text-xs">
              <thead className="sticky top-0 border-b border-edge/50 bg-surface/50">
                <tr className="text-slate-300 font-semibold">
                  <th className="px-2 py-1 text-left">Time</th>
                  <th className="px-2 py-1 text-left">Event</th>
                  <th className="px-2 py-1 text-left">Camera</th>
                  <th className="px-2 py-1 text-left">Severity</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-edge/30">
                {filtered.slice(0, 10).map((inc) => (
                  <tr key={inc.id} className="even:bg-white/[0.02] hover:bg-steel/5">
                    <td className="px-2 py-1 font-mono text-slate-400">{inc.clockLabel}</td>
                    <td className="px-2 py-1 text-slate-300">{inc.event}</td>
                    <td className="px-2 py-1 text-gold-soft">CAM {inc.cameraIndex}</td>
                    <td className="px-2 py-1">
                      <span
                        style={{ color: SEVERITY_META[inc.severity].color, fontSize: '10px', fontWeight: 'bold' }}
                      >
                        {SEVERITY_META[inc.severity].label}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Email Report modal (mock) */}
      {emailOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md animate-confirm-pop rounded-xl border border-edge/60 bg-deep/95 p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="hud-label text-sm font-bold text-gold-soft">EMAIL REPORT</h2>
              <button className="btn-icon" onClick={() => setEmailOpen(false)} title="Close">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-3">
              <div className="rounded border border-cyan/30 bg-cyan/5 px-3 py-2 text-[10px] text-cyan">
                DEMO MODE — sending is simulated. Payload is logged to the browser console.
              </div>
              <label className="text-[10px] font-semibold text-slate-400">RECIPIENT EMAIL</label>
              <input
                type="email"
                value={emailTo}
                onChange={(e) => setEmailTo(e.target.value)}
                placeholder="duty.officer@pnssafecity.pk"
                className="w-full rounded-lg border border-edge2/50 bg-surface/60 px-2 py-1.5 text-xs text-slate-200 focus:border-cyan/60 focus:outline-none"
              />
              <div className="text-[11px] text-slate-400">
                Attaching: <span className="text-gold-soft">{rangeLabel}</span> · {totalIncidents} incidents
              </div>
              {emailSent ? (
                <div className="rounded border border-okay/40 bg-okay/10 px-3 py-2 text-center text-xs font-semibold text-okay">
                  ✓ Report dispatched to {emailTo} (demo)
                </div>
              ) : (
                <button
                  onClick={sendEmail}
                  disabled={!emailTo.trim()}
                  className="btn-gold w-full disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Send className="h-4 w-4" />
                  Send Report
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
