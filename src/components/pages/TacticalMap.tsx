import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Edit3, Upload, X, Check, Trash2, ScanLine, CheckSquare, Square, Plus, Minus, Maximize2, Flame } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import { AI_MODELS } from '../../constants'
import type { Camera } from '../../types'
import { loadMapImage, saveMapImage, saveCameraPins } from '../../lib/storage'
import { filterByRange, rangeFor } from '../../lib/reportPeriod'
import { SURVEY_META } from '../../data/navalAnchorageSurvey'
import {
  CAMERA_SITES,
  HEAT_SIGMA_M,
  INVALID_SITES,
  MAP_EXTENT,
  TRACK_XY,
  incidentHeat,
  loadCameraSiteOverrides,
  renderHeatImage,
  saveCameraSiteOverrides,
  siteFor,
  siteIdFor,
  type CameraSiteOverrides,
} from '../../lib/geo'

// Site-plan view: the detailed Naval Anchorage master-plan SVG (in public/).
// It is NOT georeferenced (rotated schematic), so it keeps the legacy
// percentage pins; geographic placement uses the Geo Map view.
const DEFAULT_MAP_SRC = '/naval-anchorage-map(1).svg'

type MapView = 'geo' | 'plan'

/** Visible map window in projected metres; height follows the container aspect. */
interface ViewBox {
  x: number
  y: number
  w: number
}

const MIN_VIEW_W = 120
const MAX_VIEW_W = Math.max(MAP_EXTENT.width, MAP_EXTENT.height) * 2

interface EditingPin {
  cam: Camera
}

export default function TacticalMap() {
  const {
    cameras,
    now,
    moveCamera,
    updateCameraDetails,
    setCameraModels,
    openForensic,
    canEdit,
    incidents,
    setCameraVideo,
    reportPeriod,
    customRange,
  } = useApp()

  const [view, setView] = useState<MapView>('geo')
  const [showHeat, setShowHeat] = useState(false)
  const [siteOverrides, setSiteOverrides] = useState<CameraSiteOverrides>(() => loadCameraSiteOverrides())
  const [hoverSite, setHoverSite] = useState<string | null>(null)
  const [draftSiteId, setDraftSiteId] = useState<string>('')
  const [editMode, setEditMode] = useState(false)
  // Custom uploaded image overrides the default SVG.
  const [mapImage, setMapImage] = useState<string | null>(() => loadMapImage())
  const [editingPin, setEditingPin] = useState<EditingPin | null>(null)
  const [hoverCam, setHoverCam] = useState<string | null>(null)

  // draft fields for the config modal
  const [draftName, setDraftName] = useState('')
  const [draftIp, setDraftIp] = useState('')
  const [draftModels, setDraftModels] = useState<string[]>([])
  const [draftVideoUrl, setDraftVideoUrl] = useState('')

  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const videoInputRef = useRef<HTMLInputElement | null>(null)

  // persist custom pin positions (x/y percentages) keyed by camera id.
  useEffect(() => {
    const pins: Record<string, { x: number; y: number }> = {}
    cameras.forEach((c) => { pins[c.id] = { x: c.x, y: c.y } })
    saveCameraPins(pins)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameras])

  // Real-time pulsing pins: any incident fired in the last 60s (not yet
  // acknowledged) makes its camera pulse red (high) or amber (medium).
  const activeAlerts = useCallback(
    (camId: string) => {
      const recent = incidents.filter(
        (i) => i.cameraId === camId && !i.acknowledged && now - i.firedAt < 60_000,
      )
      if (recent.length === 0) return null
      const hasHigh = recent.some((i) => i.severity === 'high')
      return hasHigh ? 'high' : 'medium'
    },
    [incidents, now],
  )

  /* ── Geo view: viewport, pan & zoom ─────────────────────────────────── */
  const mapRef = useRef<HTMLDivElement | null>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [vb, setVb] = useState<ViewBox | null>(null)
  const dragRef = useRef<{ px: number; py: number; vb: ViewBox } | null>(null)

  const fitView = useCallback((w: number, h: number): ViewBox => {
    const aspect = h / w
    const vw = Math.max(MAP_EXTENT.width, MAP_EXTENT.height / aspect)
    return {
      x: MAP_EXTENT.minX + MAP_EXTENT.width / 2 - vw / 2,
      y: MAP_EXTENT.minY + MAP_EXTENT.height / 2 - (vw * aspect) / 2,
      w: vw,
    }
  }, [])

  useLayoutEffect(() => {
    const el = mapRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) setSize({ w: width, h: height })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [view])

  useEffect(() => {
    if (size.w > 0 && !vb) setVb(fitView(size.w, size.h))
  }, [size, vb, fitView])

  const vbH = vb && size.w > 0 ? (vb.w * size.h) / size.w : 0
  const toScreen = useCallback(
    (p: { x: number; y: number }) =>
      vb ? { left: ((p.x - vb.x) / vb.w) * size.w, top: ((p.y - vb.y) / vb.w) * size.w } : { left: 0, top: 0 },
    [vb, size.w],
  )

  const zoomAt = useCallback(
    (factor: number, sx?: number, sy?: number) => {
      setVb((cur) => {
        if (!cur || size.w === 0) return cur
        const w = Math.min(MAX_VIEW_W, Math.max(MIN_VIEW_W, cur.w * factor))
        const fx = (sx ?? size.w / 2) / size.w
        const fy = (sy ?? size.h / 2) / size.h
        const curH = (cur.w * size.h) / size.w
        const h = (w * size.h) / size.w
        return { x: cur.x + (cur.w - w) * fx, y: cur.y + (curH - h) * fy, w }
      })
    },
    [size],
  )

  // Native wheel listener: React's onWheel is passive and can't preventDefault.
  useEffect(() => {
    const el = mapRef.current
    if (!el || view !== 'geo') return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      zoomAt(e.deltaY > 0 ? 1.2 : 1 / 1.2, e.clientX - rect.left, e.clientY - rect.top)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [view, zoomAt])

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (view !== 'geo' || !vb || (e.target as HTMLElement).closest('button')) return
    dragRef.current = { px: e.clientX, py: e.clientY, vb }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = dragRef.current
    if (!d || size.w === 0) return
    const mPerPx = d.vb.w / size.w
    setVb({ ...d.vb, x: d.vb.x - (e.clientX - d.px) * mPerPx, y: d.vb.y - (e.clientY - d.py) * mPerPx })
  }
  const onPointerUp = () => { dragRef.current = null }

  /* ── Survey site linkage ────────────────────────────────────────────── */
  const camSite = useCallback((cam: Camera) => siteFor(cam, siteOverrides), [siteOverrides])
  const camsBySite = useMemo(() => {
    const m = new Map<string, Camera[]>()
    for (const c of cameras) {
      const id = siteIdFor(c.id, siteOverrides)
      if (id) m.set(id, [...(m.get(id) ?? []), c])
    }
    return m
  }, [cameras, siteOverrides])
  const unplaced = cameras.filter((c) => !camSite(c))

  /* ── Site name labels (surveyed names, verbatim) ─────────────────────────
   * Greedy collision-free placement in screen space: sites with a live feed
   * first, then survey order. Each label tries right / left / above / below
   * its marker and is skipped if it would overlap a marker, another label or
   * a map overlay — zooming in frees space, so more names appear.
   */
  const labelCtx = useMemo(() => document.createElement('canvas').getContext('2d'), [])
  const siteLabels = useMemo(() => {
    const placed: { key: string; text: string; left: number; top: number; linked: boolean }[] = []
    if (!vb || size.w === 0 || view !== 'geo') return placed
    const H = 16
    const EDGE = 6
    const textWidth = (t: string, bold: boolean) => {
      if (!labelCtx) return t.length * 5.8
      labelCtx.font = `${bold ? 600 : 500} 10px Inter, "Segoe UI", system-ui, sans-serif`
      return labelCtx.measureText(t).width
    }
    type Box = { x: number; y: number; w: number; h: number }
    const items = CAMERA_SITES.map((s) => {
      const cams = camsBySite.get(s.siteId) ?? []
      const text = cams.length > 0 ? `${cams.map((c) => `CAM ${c.index}`).join(', ')} · ${s.name}` : s.name
      return { s, cams, text, p: toScreen(s.pos) }
    }).filter(({ p }) => p.left >= 0 && p.top >= 0 && p.left <= size.w && p.top <= size.h)
    items.sort((a, b) => Number(b.cams.length > 0) - Number(a.cams.length > 0) || a.s.n - b.s.n)

    // Obstacles: every marker, plus the fixed overlays (zoom stack, scale bar, legend, warnings).
    const boxes: Box[] = items.map(({ p, cams }) => {
      const r = cams.length > 0 ? 13 : 7
      return { x: p.left - r, y: p.top - r, w: r * 2, h: r * 2 }
    })
    boxes.push({ x: size.w - 60, y: 0, w: 60, h: 180 })
    boxes.push({ x: size.w - 150, y: size.h - 64, w: 150, h: 64 })
    boxes.push({ x: 0, y: size.h - (showHeat ? 300 : 190), w: 290, h: showHeat ? 300 : 190 })
    if (unplaced.length > 0 || INVALID_SITES.length > 0) boxes.push({ x: 0, y: 0, w: 280, h: 80 })
    const hits = (b: Box) =>
      b.x < EDGE || b.y < EDGE || b.x + b.w > size.w - EDGE || b.y + b.h > size.h - EDGE ||
      boxes.some((o) => b.x < o.x + o.w && b.x + b.w > o.x && b.y < o.y + o.h && b.y + b.h > o.y)

    for (const { s, cams, text, p } of items) {
      const linked = cams.length > 0
      const w = textWidth(text, linked) + 10 // px-1 padding + border
      const gap = linked ? 14 : 8
      const candidates: Box[] = [
        { x: p.left + gap, y: p.top - H / 2, w, h: H },
        { x: p.left - gap - w, y: p.top - H / 2, w, h: H },
        { x: p.left - w / 2, y: p.top - gap - H, w, h: H },
        { x: p.left - w / 2, y: p.top + gap, w, h: H },
      ]
      const spot = candidates.find((c) => !hits(c))
      if (!spot) continue
      boxes.push(spot)
      placed.push({ key: s.siteId, text, left: spot.x, top: spot.y, linked })
    }
    return placed
  }, [vb, size, view, labelCtx, camsBySite, toScreen, showHeat, unplaced.length])
  const labelledSites = useMemo(() => new Set(siteLabels.map((l) => l.key)), [siteLabels])

  /* ── Incident heatmap (reuses the shared Incident Log / Analytics period) ── */
  const range = useMemo(() => rangeFor(reportPeriod, now, customRange ?? undefined), [reportPeriod, now, customRange])
  const heat = useMemo(
    () => incidentHeat(filterByRange(incidents, range), cameras, siteOverrides),
    [incidents, range, cameras, siteOverrides],
  )
  const heatKey = heat.points.map((p) => `${p.siteId}:${p.weight}`).join('|')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const heatImage = useMemo(() => (showHeat ? renderHeatImage(heat.points) : null), [showHeat, heatKey])

  const handleMapUpload = (file: File) => {
    const url = URL.createObjectURL(file)
    setView('plan')
    setMapImage(url)
    const reader = new FileReader()
    reader.onload = () => saveMapImage(String(reader.result))
    reader.readAsDataURL(file)
  }

  const handleMapClick = (e: React.MouseEvent<HTMLDivElement>) => {
    // Geo view positions come from the GPS survey — no click-to-relocate there.
    if (!editMode || view !== 'plan') return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = Math.min(100, Math.max(0, ((e.clientX - rect.left) / rect.width) * 100))
    const y = Math.min(100, Math.max(0, ((e.clientY - rect.top) / rect.height) * 100))

    let nearest: Camera | null = null
    let nearestDist = 4
    for (const c of cameras) {
      const d = Math.hypot(c.x - x, c.y - y)
      if (d < nearestDist) { nearestDist = d; nearest = c }
    }
    if (nearest) { openConfig(nearest); return }

    let farthest: Camera = cameras[0]
    let farthestDist = -1
    for (const c of cameras) {
      const d = Math.hypot(c.x - x, c.y - y)
      if (d > farthestDist) { farthestDist = d; farthest = c }
    }
    moveCamera(farthest.id, x, y)
  }

  const openConfig = (cam: Camera) => {
    setEditingPin({ cam })
    setDraftName(cam.name)
    setDraftIp(cam.ip)
    setDraftModels([...cam.models])
    setDraftVideoUrl(cam.videoUrl)
    setDraftSiteId(siteIdFor(cam.id, siteOverrides) ?? '')
  }

  const savePin = () => {
    if (!editingPin) return
    const id = editingPin.cam.id
    updateCameraDetails(id, { name: draftName || editingPin.cam.name, ip: draftIp || editingPin.cam.ip })
    setCameraModels(id, draftModels)
    if ((siteIdFor(id, siteOverrides) ?? '') !== draftSiteId) {
      const next = { ...siteOverrides, [id]: draftSiteId || null }
      setSiteOverrides(next)
      saveCameraSiteOverrides(next)
    }
    setEditingPin(null)
  }

  const updateModels = (modelId: string) => {
    setDraftModels((prev) =>
      prev.includes(modelId) ? prev.filter((m) => m !== modelId) : [...prev, modelId],
    )
  }

  const handleVideoUpload = (file: File) => {
    const url = URL.createObjectURL(file)
    setDraftVideoUrl(url)
    if (editingPin) setCameraVideo(editingPin.cam.id, url)
  }

  // Active map source: custom upload beats the default detailed SVG
  const mapSrc = mapImage ?? DEFAULT_MAP_SRC

  // Camera pin — shared by both views; only the anchor position differs.
  const renderPin = (cam: Camera, pos: React.CSSProperties, showCamLabel = true) => {
    const alert = activeAlerts(cam.id)
    const hovered = hoverCam === cam.id
    const site = camSite(cam)

    // Dot colour: red on critical, amber on warning, green = online (live feed linked)
    const dotColour = alert === 'high' ? '#EF4444' : alert === 'medium' ? '#F59E0B' : '#22C55E'
    const ringColour =
      alert === 'high' ? 'rgba(239,68,68,0.45)' : alert === 'medium' ? 'rgba(245,158,11,0.45)' : 'rgba(34,197,94,0.4)'
    const glowShadow = alert ? `0 0 8px 2px ${ringColour}` : '0 1px 3px rgba(0,0,0,0.6)'

    return (
      <div
        key={cam.id}
        className={`absolute -translate-x-1/2 -translate-y-1/2 ${hovered ? 'z-30' : 'z-10'}`}
        style={pos}
      >
        {/* Outer ring — animated on alert, static otherwise so the pin stays visible */}
        {alert ? (
          <span
            className="absolute -inset-3 rounded-full animate-pin-ping"
            style={{ backgroundColor: ringColour }}
          />
        ) : (
          <span
            className="absolute rounded-full"
            style={{
              inset: '-5px',
              backgroundColor: 'rgba(34,197,94,0.12)',
              border: '1px solid rgba(34,197,94,0.35)',
              borderRadius: '50%',
            }}
          />
        )}

        <button
          onClick={(e) => {
            e.stopPropagation()
            if (editMode) {
              openConfig(cam)
            } else {
              openForensic(cam.id)
            }
          }}
          onMouseEnter={() => setHoverCam(cam.id)}
          onMouseLeave={() => setHoverCam(null)}
          className="relative flex items-center justify-center rounded-full transition-transform hover:scale-125 focus:outline-none"
          style={{
            width: 16,
            height: 16,
            backgroundColor: dotColour,
            boxShadow: glowShadow,
            border: '2px solid #F1F5F9',
          }}
          title={`${cam.name} · ${cam.ip}`}
        />

        {/* CAM label below the dot (geo view uses the full site label instead) */}
        {showCamLabel && <div
          className="pointer-events-none absolute left-1/2 -translate-x-1/2 whitespace-nowrap text-center font-bold"
          style={{
            top: 18,
            fontSize: 9,
            color: '#F1F5F9',
            textShadow: '0 1px 3px rgba(0,0,0,0.9)',
            letterSpacing: '0.04em',
          }}
        >
          CAM {cam.index}
        </div>}

        {hovered && !editMode && (
          <div className="pointer-events-none absolute left-1/2 top-full z-30 mt-4 w-56 -translate-x-1/2 rounded-lg border border-edge bg-surface p-2.5 text-[10px] shadow-panel">
            {alert && (
              <div
                className="mb-2 flex items-center gap-1.5 rounded px-2 py-1 text-[9px] font-bold"
                style={{
                  backgroundColor: alert === 'high' ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.15)',
                  color: alert === 'high' ? '#EF4444' : '#F59E0B',
                  border: `1px solid ${alert === 'high' ? 'rgba(239,68,68,0.4)' : 'rgba(245,158,11,0.4)'}`,
                }}
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ backgroundColor: alert === 'high' ? '#EF4444' : '#F59E0B' }}
                />
                {alert === 'high' ? 'CRITICAL ALERT' : 'WARNING ALERT'}
              </div>
            )}
            <div className="font-bold text-gold-soft">CAM {cam.index}</div>
            <div className="mt-0.5 text-slate-200">{cam.name}</div>
            <div className="mt-0.5 font-mono text-cyan">{cam.ip}</div>
            <div className="mt-1 text-slate-500">{cam.zone}</div>
            {view === 'geo' && site && (
              <div className="mt-1.5 border-t border-edge pt-1.5 text-slate-400">
                <div>Site {site.siteId} · {site.name}</div>
                <div className="font-mono text-slate-500">{site.lat.toFixed(6)}, {site.lon.toFixed(6)}</div>
              </div>
            )}
            {cam.models.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {cam.models.map((mid) => (
                  <span
                    key={mid}
                    className="rounded border border-edge2/50 bg-surface2/50 px-1 py-px text-[8px] font-semibold text-slate-300"
                  >
                    {mid.toUpperCase()}
                  </span>
                ))}
              </div>
            )}
            <div className="mt-2 text-[8px] text-slate-500 italic">Click to open forensic view</div>
          </div>
        )}
      </div>
    )
  }

  // Scale bar: largest "nice" length that fits in ~110 px at the current zoom.
  const mPerPx = vb && size.w > 0 ? vb.w / size.w : 0
  const scaleM = mPerPx > 0 ? [50, 100, 200, 250, 500, 1000, 2000].filter((m) => m / mPerPx <= 110).pop() ?? 50 : 0

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto bg-base p-6">

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="hud-label text-2xl text-gold-soft">TACTICAL SURVEILLANCE MAP</h1>
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
          <div className="mr-2">{new Date(now).toLocaleString('en-GB', { hour12: false })}</div>
          {/* View switch: geographic (GPS survey) vs. legacy site-plan image */}
          <div className="inline-flex overflow-hidden rounded-lg border border-edge">
            {(['geo', 'plan'] as const).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`px-3 py-1.5 text-xs font-semibold transition ${
                  view === v ? 'bg-gold/15 text-gold-soft' : 'bg-surface text-slate-400 hover:text-slate-200'
                }`}
                title={v === 'geo' ? 'Geographic map from the GPS camera survey' : 'Master-plan image (not to geographic scale)'}
              >
                {v === 'geo' ? 'Geo Map' : 'Site Plan'}
              </button>
            ))}
          </div>
          {view === 'geo' && (
            <button
              onClick={() => setShowHeat((v) => !v)}
              className={`btn gap-2 text-xs ${showHeat ? 'border-gold/60 bg-gold/15 text-gold-soft' : ''}`}
              title="Toggle incident heatmap (uses the Incident Log reporting period)"
            >
              <Flame className="h-4 w-4" />
              Heatmap
            </button>
          )}
          {canEdit && (
            <>
              <button
                onClick={() => fileInputRef.current?.click()}
                className="btn gap-2 text-xs"
                title="Upload a custom map image (JPG/PNG/SVG) for the Site Plan view"
              >
                <Upload className="h-4 w-4" />
                Upload Map
              </button>
              {mapImage && (
                <button
                  onClick={() => { setMapImage(null); saveMapImage(null) }}
                  className="btn gap-2 text-xs border-slate-600/50 text-slate-400 hover:border-danger/50 hover:text-danger"
                  title="Revert to Naval Anchorage base map"
                >
                  Reset Map
                </button>
              )}
              <button
                onClick={() => setEditMode((v) => !v)}
                className={`btn gap-2 text-xs ${editMode ? 'border-gold/60 bg-gold/15 text-gold-soft' : ''}`}
                title={editMode ? 'Exit edit mode' : 'Enter edit mode — configure pins'}
              >
                {editMode ? <Check className="h-4 w-4" /> : <Edit3 className="h-4 w-4" />}
                {editMode ? 'Done' : 'Edit Mode'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* ── Map ── */}
      <div
        ref={mapRef}
        className={`relative flex-1 overflow-hidden rounded-xl border border-edge bg-deep shadow-panel ${
          view === 'geo' ? 'cursor-grab touch-none active:cursor-grabbing' : ''
        }`}
        style={{ minHeight: '55vh' }}
        onClick={handleMapClick}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {view === 'plan' ? (
          <>
            {/* Background map image */}
            <img
              src={mapSrc}
              alt="Naval Anchorage Islamabad — surveillance map"
              className="pointer-events-none absolute inset-0 h-full w-full object-cover"
              draggable={false}
            />
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_55%,rgba(8,15,28,0.45)_100%)]" />
            {cameras.map((cam) => renderPin(cam, { left: `${cam.x}%`, top: `${cam.y}%` }))}
            <div className="pointer-events-none absolute right-3 top-3 z-10 rounded-md border border-edge bg-deep px-2.5 py-1.5 text-[10px] text-slate-400">
              Site plan — schematic, not to geographic scale
            </div>
          </>
        ) : (
          vb && (
            <>
              {/* Survey track + heat share one metre-based viewBox with the markers */}
              <svg
                className="pointer-events-none absolute inset-0 h-full w-full"
                viewBox={`${vb.x} ${vb.y} ${vb.w} ${vbH}`}
                preserveAspectRatio="none"
              >
                <defs>
                  <pattern id="geo-grid" width="250" height="250" patternUnits="userSpaceOnUse" x={MAP_EXTENT.minX} y={MAP_EXTENT.minY}>
                    <path d="M250 0H0V250" fill="none" stroke="var(--border-edge)" strokeWidth={mPerPx * 0.6} opacity="0.55" />
                  </pattern>
                </defs>
                <rect x={vb.x} y={vb.y} width={vb.w} height={vbH} fill="url(#geo-grid)" />
                {TRACK_XY.map((seg, i) => (
                  <polyline
                    key={`c${i}`}
                    points={seg.map((p) => `${p.x},${p.y}`).join(' ')}
                    fill="none"
                    stroke="#293B52"
                    strokeWidth={Math.max(mPerPx * 7, 9)}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                ))}
                {TRACK_XY.map((seg, i) => (
                  <polyline
                    key={`l${i}`}
                    points={seg.map((p) => `${p.x},${p.y}`).join(' ')}
                    fill="none"
                    stroke="#3E5574"
                    strokeWidth={Math.max(mPerPx * 2.5, 3)}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                ))}
                {heatImage && (
                  <image
                    href={heatImage}
                    x={MAP_EXTENT.minX}
                    y={MAP_EXTENT.minY}
                    width={MAP_EXTENT.width}
                    height={MAP_EXTENT.height}
                    preserveAspectRatio="none"
                  />
                )}
              </svg>

              {/* Surveyed sites without a linked feed (gray) */}
              {CAMERA_SITES.filter((s) => !camsBySite.has(s.siteId)).map((s) => {
                const p = toScreen(s.pos)
                const hovered = hoverSite === s.siteId
                return (
                  <div
                    key={s.siteId}
                    className={`absolute -translate-x-1/2 -translate-y-1/2 ${hovered ? 'z-20' : 'z-[5]'}`}
                    style={{ left: p.left, top: p.top }}
                    onMouseEnter={() => setHoverSite(s.siteId)}
                    onMouseLeave={() => setHoverSite(null)}
                  >
                    <span
                      className="block h-2.5 w-2.5 rounded-full"
                      style={{ backgroundColor: '#64748B', border: '1.5px solid #94A3B8' }}
                    />
                    {hovered && (
                      <div className="pointer-events-none absolute left-1/2 top-full mt-2 w-52 -translate-x-1/2 rounded-lg border border-edge bg-surface p-2 text-[10px] shadow-panel">
                        <div className="font-semibold text-slate-200">{s.name}</div>
                        <div className="mt-0.5 text-slate-400">Surveyed site {s.siteId} · no feed linked</div>
                        <div className="mt-0.5 font-mono text-slate-500">{s.lat.toFixed(6)}, {s.lon.toFixed(6)}</div>
                      </div>
                    )}
                  </div>
                )
              })}

              {/* Linked camera feeds at their surveyed GPS position */}
              {cameras.map((cam) => {
                const site = camSite(cam)
                if (!site) return null
                const p = toScreen(site.pos)
                return renderPin(cam, { left: p.left, top: p.top }, !labelledSites.has(site.siteId))
              })}

              {/* Surveyed names, verbatim from the GPS survey */}
              {siteLabels.map((l) => (
                <div
                  key={`lbl-${l.key}`}
                  className={`pointer-events-none absolute z-[6] whitespace-nowrap rounded border px-1 ${
                    l.linked
                      ? 'border-okay/40 bg-deep/90 font-semibold text-slate-100'
                      : 'border-transparent bg-deep/75 font-medium text-slate-300'
                  }`}
                  style={{ left: l.left, top: l.top, height: 16, fontSize: 10, lineHeight: '14px' }}
                >
                  {l.text}
                </div>
              ))}

              {/* Zoom controls + north arrow */}
              <div className="absolute right-3 top-3 z-20 flex flex-col gap-1">
                <button className="btn-icon" onClick={() => zoomAt(1 / 1.5)} title="Zoom in"><Plus className="h-4 w-4" /></button>
                <button className="btn-icon" onClick={() => zoomAt(1.5)} title="Zoom out"><Minus className="h-4 w-4" /></button>
                <button className="btn-icon" onClick={() => setVb(fitView(size.w, size.h))} title="Fit Naval Anchorage"><Maximize2 className="h-4 w-4" /></button>
                <div className="mt-1 flex h-8 w-8 flex-col items-center justify-center rounded-lg border border-edge bg-surface text-[9px] font-bold text-slate-300" title="Map is north-up">
                  <span className="leading-none">▲</span>N
                </div>
              </div>

              {/* Scale bar */}
              {scaleM > 0 && (
                <div className="pointer-events-none absolute bottom-3 right-3 z-10 rounded-md border border-edge bg-deep px-2 py-1 text-[10px] text-slate-400">
                  <div className="h-1.5 border-x border-b border-slate-400" style={{ width: scaleM / mPerPx }} />
                  <div className="mt-0.5 text-center">{scaleM >= 1000 ? `${scaleM / 1000} km` : `${scaleM} m`}</div>
                </div>
              )}

              {/* Unplaced cameras / invalid survey rows — reported, never placed at dummy spots */}
              {(unplaced.length > 0 || INVALID_SITES.length > 0) && (
                <div className="absolute left-3 top-3 z-10 max-w-[260px] rounded-lg border border-warn/40 bg-deep px-3 py-2 text-[10px]">
                  {unplaced.length > 0 && (
                    <>
                      <div className="font-bold uppercase tracking-wider text-warn">No surveyed site — not placed</div>
                      <div className="mt-1 text-slate-400">
                        {unplaced.map((c) => `CAM ${c.index}`).join(', ')}
                        {canEdit && ' · assign via Site Plan → Edit Mode → click pin'}
                      </div>
                    </>
                  )}
                  {INVALID_SITES.length > 0 && (
                    <div className="mt-1 text-danger">
                      Invalid GPS in survey: {INVALID_SITES.map((w) => `#${w.n} ${w.name}`).join(', ')}
                    </div>
                  )}
                </div>
              )}
            </>
          )
        )}

        {/* Edit mode hint */}
        {editMode && (
          <div className="pointer-events-none absolute left-1/2 top-3 z-20 -translate-x-1/2 rounded-lg border border-gold/50 bg-surface px-4 py-2 text-[11px] font-semibold text-gold-soft shadow-lg">
            {view === 'plan'
              ? 'EDIT MODE — click a pin to configure · click empty area to relocate'
              : 'EDIT MODE — click a pin to configure its camera and surveyed GPS site'}
          </div>
        )}

        {/* Legend */}
        <div className="pointer-events-none absolute bottom-3 left-3 z-10 flex max-w-[270px] flex-col gap-1.5 rounded-lg border border-edge bg-deep px-3 py-2.5">
          <div className="mb-1 text-[9px] font-bold uppercase tracking-widest text-slate-500">Legend</div>
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full" style={{ backgroundColor: '#22C55E', border: '2px solid #F1F5F9' }} />
            <span className="text-[10px] text-slate-400">Camera online (live feed)</span>
          </div>
          {view === 'geo' && (
            <div className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: '#64748B', border: '1.5px solid #94A3B8' }} />
              <span className="text-[10px] text-slate-400">Surveyed camera site (no feed linked)</span>
            </div>
          )}
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full" style={{ backgroundColor: '#EF4444', border: '2px solid #F1F5F9' }} />
            <span className="text-[10px] text-slate-400">Critical alert</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full" style={{ backgroundColor: '#F59E0B', border: '2px solid #F1F5F9' }} />
            <span className="text-[10px] text-slate-400">Warning alert</span>
          </div>
          {view === 'geo' && (
            <div className="flex items-center gap-2">
              <span className="h-1 w-4 rounded" style={{ backgroundColor: '#3E5574' }} />
              <span className="text-[10px] text-slate-400">GPS-surveyed road</span>
            </div>
          )}
          {view === 'geo' && showHeat && (
            <div className="mt-1 border-t border-edge pt-1.5 text-[9px] leading-snug text-slate-400">
              <div className="mb-1 font-bold uppercase tracking-wider text-slate-500">Incident heat · {range.label}</div>
              <div
                className="h-1.5 w-full rounded"
                style={{ background: 'linear-gradient(90deg,#16B8D4,#EAB308,#F97316,#EF4444)' }}
              />
              <div className="mt-0.5 flex justify-between text-slate-500"><span>Low</span><span>Critical</span></div>
              <div className="mt-1">
                {heat.mapped} incident{heat.mapped === 1 ? '' : 's'} mapped
                {heat.unmapped > 0 && ` · ${heat.unmapped} without a camera site`}
              </div>
              <div className="text-slate-500">
                Located at the reporting camera's site (approximate, not exact incident GPS).
                Weight: critical 3 · warning 2 · advisory 1; σ {HEAT_SIGMA_M} m; colour relative to peak.
              </div>
              {heat.mapped === 0 && <div className="text-slate-500">No incidents in this period.</div>}
            </div>
          )}
          {view === 'geo' && (
            <div className="mt-1 text-[8px] text-slate-500">
              GPS survey {SURVEY_META.trackStart.slice(0, 10)} · {SURVEY_META.datum} · {CAMERA_SITES.length} sites
            </div>
          )}
        </div>
      </div>

      {/* Camera status grid */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {cameras.map((cam) => {
          const alert = activeAlerts(cam.id)
          return (
            <div
              key={cam.id}
              className={`rounded-lg border p-3 text-sm transition ${
                alert === 'high'
                  ? 'border-danger/50 bg-danger/8'
                  : alert === 'medium'
                    ? 'border-warn/50 bg-warn/8'
                    : 'border-edge bg-surface'
              }`}
            >
              <div className="mb-1.5 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {/* Status dot: green online, red critical, amber warning */}
                  <span
                    className={`h-2.5 w-2.5 rounded-full flex-shrink-0 ${alert ? 'animate-pulse' : ''}`}
                    style={{
                      backgroundColor: alert === 'high' ? '#EF4444' : alert === 'medium' ? '#F59E0B' : '#22C55E',
                      border: '1.5px solid rgba(241,245,249,0.6)',
                    }}
                  />
                  <span className="font-bold text-gold-soft text-xs">CAM {cam.index}</span>
                </div>
                <button
                  className="btn-icon h-6 w-6"
                  title="Open forensic playback"
                  onClick={() => openForensic(cam.id)}
                >
                  <ScanLine className="h-3 w-3" />
                </button>
              </div>
              <div className="text-[10px] text-slate-400 space-y-0.5">
                <div className="truncate font-medium text-slate-300">{cam.name}</div>
                <div className="font-mono text-cyan">{cam.ip}</div>
                <div className="text-slate-500">{cam.zone}</div>
                {(() => {
                  const site = camSite(cam)
                  return (
                    <div className={`truncate ${site ? 'text-slate-300' : 'text-warn'}`} title={site ? `${site.lat}, ${site.lon}` : undefined}>
                      {site ? `Site ${site.siteId} · ${site.name}` : 'No surveyed site — not on map'}
                    </div>
                  )
                })()}
              </div>
              {alert && (
                <div
                  className="mt-1.5 rounded px-1.5 py-0.5 text-[9px] font-bold"
                  style={{
                    backgroundColor: alert === 'high' ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.15)',
                    color: alert === 'high' ? '#EF4444' : '#F59E0B',
                  }}
                >
                  {alert === 'high' ? '⚠ CRITICAL' : '▲ WARNING'}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Hidden file inputs */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*,.svg"
        className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleMapUpload(f); e.target.value = '' }}
      />
      <input
        ref={videoInputRef}
        type="file"
        accept="video/mp4"
        className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleVideoUpload(f); e.target.value = '' }}
      />

      {/* Pin config modal */}
      {editingPin && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md animate-confirm-pop rounded-xl border border-edge/60 bg-deep p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="hud-label text-sm font-bold text-gold-soft">
                CONFIGURE CAMERA — CAM {editingPin.cam.index}
              </h2>
              <button className="btn-icon" onClick={() => setEditingPin(null)} title="Close">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-[10px] font-semibold text-slate-400">CAMERA NAME</label>
                <input
                  value={draftName}
                  onChange={(e) => setDraftName(e.target.value)}
                  className="w-full rounded-lg border border-edge2/50 bg-surface/60 px-2 py-1.5 text-xs text-slate-200 focus:border-cyan/60 focus:outline-none"
                />
              </div>
              <div>
                <label className="text-[10px] font-semibold text-slate-400">IP ADDRESS</label>
                <input
                  value={draftIp}
                  onChange={(e) => setDraftIp(e.target.value)}
                  className="w-full rounded-lg border border-edge2/50 bg-surface/60 px-2 py-1.5 text-xs font-mono text-cyan focus:border-cyan/60 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-[10px] font-semibold text-slate-400">ACTIVE AI MODELS</label>
                <div className="mt-1 grid grid-cols-2 gap-1.5">
                  {AI_MODELS.map((m) => {
                    const active = draftModels.includes(m.id)
                    return (
                      <button
                        key={m.id}
                        onClick={() => updateModels(m.id)}
                        className={`flex items-center gap-1.5 rounded border px-2 py-1 text-[10px] font-semibold transition ${
                          active
                            ? 'border-gold/60 bg-gold/15 text-gold-soft'
                            : 'border-edge2/40 bg-surface/40 text-slate-400 hover:border-edge2/70'
                        }`}
                      >
                        {active ? <CheckSquare className="h-3 w-3" /> : <Square className="h-3 w-3" />}
                        {m.short}
                      </button>
                    )
                  })}
                </div>
              </div>

              <div>
                <label className="text-[10px] font-semibold text-slate-400">LINKED VIDEO STREAM</label>
                <div className="mt-1 flex items-center gap-2">
                  <button onClick={() => videoInputRef.current?.click()} className="btn gap-2 text-xs flex-1">
                    <Upload className="h-4 w-4" />
                    {draftVideoUrl ? 'Replace .mp4' : 'Upload .mp4'}
                  </button>
                  {draftVideoUrl && (
                    <span className="truncate text-[9px] text-cyan max-w-[140px]">
                      {draftVideoUrl.startsWith('blob:') ? 'local file' : 'built-in clip'}
                    </span>
                  )}
                </div>
              </div>

              <div>
                <label className="text-[10px] font-semibold text-slate-400">SURVEYED GPS SITE (GEO MAP POSITION)</label>
                <select
                  value={draftSiteId}
                  onChange={(e) => setDraftSiteId(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-edge2/50 bg-surface/60 px-2 py-1.5 text-xs text-slate-200 focus:border-cyan/60 focus:outline-none"
                >
                  <option value="">— Not placed (no surveyed site) —</option>
                  {CAMERA_SITES.map((s) => (
                    <option key={s.siteId} value={s.siteId}>
                      {s.siteId} · {s.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-center justify-between border-t border-edge/40 pt-3">
                <button
                  onClick={() => setEditingPin(null)}
                  className="btn text-xs gap-2 text-danger border-danger/40 hover:border-danger/70"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Cancel
                </button>
                <button onClick={savePin} className="btn-gold text-xs">
                  <Check className="h-3.5 w-3.5" />
                  Save Pin
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
