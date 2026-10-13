import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Upload,
  Play,
  Pause,
  Zap,
  Grid3X3,
  Grid2X2,
  Maximize2,
  ScanLine,
  LayoutDashboard,
} from 'lucide-react'
import { useApp } from '../../store/AppContext'
import type { LayoutId } from '../../types'
import { SEVERITY_META } from '../../constants'
import ModelBadge from '../ui/ModelBadge'
import ForensicPanel from '../forensics/ForensicPanel'

/* ── Layout presets ────────────────────────────────────────────────────────────
 * Slot-fill rule: "Keep current primary + fill remaining slots by camera ID order."
 * `order` is the canonical display sequence (order[0] = primary). Switching
 * presets slices `order` to the preset's tile count; the same camera-keyed
 * <video> elements keep playing across slot changes without remounting.
 *
 * focus  : 1 Main (60–70%) + right col of 3 + bottom row of 3 = 7 tiles
 * grid2x2: 2×2 = 4 tiles
 * grid3x3: 3×3 = 9 tiles
 * focus5 : 1 Main + 4 split = 5 tiles
 * full   : Single Main fullscreen = 1 tile
 */
const LAYOUTS: Record<
  LayoutId,
  {
    label: string
    count: number
    container: string
    main: string
    sub: string
  }
> = {
  focus: {
    label: '1+6 Focus',
    count: 7,
    container: 'grid-cols-4 grid-rows-3',
    main: 'col-span-2 row-span-3',
    sub: 'col-span-1 row-span-1',
  },
  grid2x2: {
    label: '2×2 Grid',
    count: 4,
    container: 'grid-cols-2 grid-rows-2',
    main: 'col-span-1 row-span-1',
    sub: 'col-span-1 row-span-1',
  },
  grid3x3: {
    label: '3×3 Grid',
    count: 9,
    container: 'grid-cols-3 grid-rows-3',
    main: 'col-span-1 row-span-1',
    sub: 'col-span-1 row-span-1',
  },
  focus5: {
    label: '1+4 Split',
    count: 5,
    container: 'grid-cols-3',
    main: 'col-span-2 row-span-2',
    sub: 'col-span-1',
  },
  full: {
    label: 'Fullscreen',
    count: 1,
    container: 'grid-cols-1 grid-rows-1',
    main: 'col-span-1 row-span-1',
    sub: 'col-span-1 row-span-1',
  },
}

/* ── Tile density ──────────────────────────────────────────────────────────── */
type TileScale = 'compact' | 'normal' | 'large'
const TILE_SCALE_OPTS: { value: TileScale; label: string }[] = [
  { value: 'compact', label: 'Compact' },
  { value: 'normal', label: 'Normal' },
  { value: 'large', label: 'Large' },
]
const TILE_SCALE_STYLE: Record<TileScale, React.CSSProperties> = {
  compact: { fontSize: '0.75rem' },
  normal: {},
  large: { fontSize: '1rem' },
}
const TILE_SCALE_GAP: Record<TileScale, string> = {
  compact: 'gap-1',
  normal: 'gap-3',
  large: 'gap-4',
}

/* ── Helpers ───────────────────────────────────────────────────────────────── */
function relTime(firedAt: number): string {
  const diff = Math.floor((Date.now() - firedAt) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}



/* ── Main component ─────────────────────────────────────────────────────────── */
export default function LiveWall() {
  const {
    cameras,
    order,
    focusCamera,
    swapTiles,
    layout,
    setLayout,
    playing,
    setPlaying,
    speed,
    setSpeed,
    openForensic,
    closeForensic,
    forensicCameraId,
    mountCustomVideo,
  } = useApp()

  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [dropTarget, setDropTarget] = useState<number | null>(null)
  const [tileScale, setTileScale] = useState<TileScale>('normal')

  const layoutDef = LAYOUTS[layout]
  const visibleIds = order.slice(0, layoutDef.count)

  const getCam = useCallback((id: string) => cameras.find((c) => c.id === id), [cameras])

  /* ── A2 FIX: sync all video[data-cam] whenever playing/speed changes ─────── */
  const playingRef = useRef(playing)
  const speedRef = useRef(speed)
  useEffect(() => { playingRef.current = playing }, [playing])
  useEffect(() => { speedRef.current = speed }, [speed])

  useEffect(() => {
    const els = document.querySelectorAll<HTMLVideoElement>('video[data-cam]')
    els.forEach((el) => {
      el.playbackRate = speed
      if (playing) {
        if (el.paused) void el.play().catch(() => {})
      } else {
        if (!el.paused) el.pause()
      }
    })
  }, [playing, speed])

  /* ── Drag-and-drop swap ──────────────────────────────────────────────────── */
  const onDrop = (toIndex: number) => {
    if (dragIndex !== null && dragIndex !== toIndex) swapTiles(dragIndex, toIndex)
    setDragIndex(null)
    setDropTarget(null)
  }

  /* ── Fullscreen ──────────────────────────────────────────────────────────── */
  const exitFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
  }

  /* ── A10 FIX: focus5 explicit row sizing so tiles don't clip ─────────────── */
  const gridStyle: React.CSSProperties =
    layout === 'focus5'
      ? { gridTemplateRows: 'repeat(2, minmax(0, 1fr))' }
      : {}



  return (
    <main className="relative flex min-h-0 flex-1 flex-col gap-3 overflow-hidden bg-base p-4">

      {/* ── Toolbar ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-edge/50 bg-surface2/60 px-4 py-3 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          {/* Play / Pause */}
          <button
            onClick={() => setPlaying(!playing)}
            className="btn-icon"
            title={playing ? 'Pause all streams' : 'Resume all streams'}
          >
            {playing ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5" />}
          </button>

          <div className="h-6 w-px bg-edge2/50" />

          {/* Speed */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400 font-semibold">SPEED:</span>
            <select
              value={speed}
              onChange={(e) => setSpeed(parseFloat(e.target.value))}
              className="btn text-xs"
            >
              <option value={1}>1×</option>
              <option value={2}>2×</option>
            </select>
          </div>

          <div className="h-6 w-px bg-edge2/50" />

          {/* Tile density */}
          <div className="flex items-center gap-2">
            <LayoutDashboard className="h-3.5 w-3.5 text-slate-400" />
            <select
              value={tileScale}
              onChange={(e) => setTileScale(e.target.value as TileScale)}
              className="btn text-xs"
              title="Tile display density"
            >
              {TILE_SCALE_OPTS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Layout presets */}
        <div className="flex flex-wrap items-center gap-2">
          {(Object.keys(LAYOUTS) as LayoutId[]).map((id) => {
            const def = LAYOUTS[id]
            const active = layout === id
            return (
              <button
                key={id}
                onClick={() => setLayout(id)}
                className={`btn text-xs ${active ? 'border-gold/60 bg-gold/15 text-gold-soft' : ''}`}
                title={def.label}
              >
                {id === 'focus' && <Zap className="h-3.5 w-3.5" />}
                {id === 'grid2x2' && <Grid2X2 className="h-3.5 w-3.5" />}
                {id === 'grid3x3' && <Grid3X3 className="h-3.5 w-3.5" />}
                {def.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* ── Video grid ── */}
      <div
        className={`grid min-h-0 flex-1 ${TILE_SCALE_GAP[tileScale]} ${layoutDef.container}`}
        style={{ ...gridStyle, ...TILE_SCALE_STYLE[tileScale] }}
      >
        {visibleIds.map((camId, idx) => {
          const cam = getCam(camId)
          if (!cam) return null

          const isMain = layout !== 'grid2x2' && layout !== 'grid3x3' && idx === 0
          const isDragSource = dragIndex === idx
          const isDropTarget = dropTarget === idx && dragIndex !== null && dragIndex !== idx

          return (
            <div
              key={camId}
              data-slot={idx}
              draggable
              onDragStart={(e) => {
                setDragIndex(idx)
                e.dataTransfer.effectAllowed = 'move'
              }}
              onDragOver={(e) => {
                e.preventDefault()
                setDropTarget(idx)
              }}
              onDragLeave={() => setDropTarget((cur) => (cur === idx ? null : cur))}
              onDrop={(e) => {
                e.preventDefault()
                onDrop(idx)
              }}
              onDragEnd={() => {
                setDragIndex(null)
                setDropTarget(null)
              }}
              onClick={() => {
                if (!isMain) focusCamera(camId)
              }}
              className={`group relative flex flex-col overflow-hidden rounded-lg border bg-base shadow-lg transition ${
                isMain ? layoutDef.main : layoutDef.sub
              } ${
                isDragSource
                  ? 'border-cyan/70 opacity-60'
                  : isDropTarget
                    ? 'border-gold/70 ring-2 ring-gold/40'
                    : isMain
                      ? 'border-gold/40'
                      : 'border-edge/60 hover:border-gold/50'
              } ${isMain ? 'cursor-default' : 'cursor-pointer'}`}
            >
              {/* Video — keyed by camera id so swaps never remount */}
              <video
                key={`video-${camId}`}
                data-cam={camId}
                src={cam.videoUrl}
                className="pointer-events-none h-full w-full bg-black object-cover"
                autoPlay
                loop
                muted
                playsInline
                ref={(el) => {
                  if (el) {
                    el.playbackRate = speedRef.current
                    if (playingRef.current && el.paused) void el.play().catch(() => {})
                    if (!playingRef.current && !el.paused) el.pause()
                  }
                }}
              />

              {/* Scanlines overlay */}
              <div className="scanlines pointer-events-none absolute inset-0" />

              {/* HUD */}
              <div className="pointer-events-none absolute inset-0 flex flex-col justify-between p-2">
                {/* Top row: badge + REC */}
                <div className="flex items-start justify-between gap-2">
                  <div className="flex flex-col gap-1">
                    <div className="hud-label text-xs font-bold text-gold-soft drop-shadow-lg">
                      CAM {cam.index}
                    </div>
                    <div className="text-[10px] text-slate-300 drop-shadow-md">{cam.zone}</div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {cam.customVideo && (
                      <span className="rounded bg-cyan/80 px-1.5 py-0.5 text-[9px] font-bold text-slate-950 font-mono">
                        CUSTOM MP4
                      </span>
                    )}
                    <div className="flex items-center gap-0.5 rounded bg-danger/80 px-2 py-0.5 animate-live-blink">
                      <div className="h-1.5 w-1.5 rounded-full bg-white" />
                      <span className="text-[10px] font-bold text-white">REC</span>
                    </div>
                  </div>
                </div>

                {/* Bottom row: controls (main only) + model badges */}
                <div className="flex flex-col items-end gap-1">
                  {/* A3 FIX: Controls only on main tile — not blocked by hover overlay */}
                  {isMain && (
                    <div className="pointer-events-auto mb-1 flex items-center gap-1">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          setPlaying(!playing)
                        }}
                        className="rounded border border-edge2/70 bg-surface/80 p-1 text-slate-200 hover:border-cyan/60 hover:text-cyan"
                        title={playing ? 'Pause stream' : 'Play stream'}
                      >
                        {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          setSpeed(speed === 1 ? 2 : 1)
                        }}
                        className={`rounded border px-1.5 py-0.5 text-[10px] font-bold ${
                          speed === 2
                            ? 'border-cyan/60 bg-cyan/15 text-cyan'
                            : 'border-edge2/70 bg-surface/80 text-slate-200 hover:border-cyan/60'
                        }`}
                        title="Toggle 1× / 2× speed"
                      >
                        {speed}×
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          exitFullscreen()
                        }}
                        className="rounded border border-edge2/70 bg-surface/80 p-1 text-slate-200 hover:border-cyan/60 hover:text-cyan"
                        title="Exit fullscreen"
                      >
                        <Maximize2 className="h-3.5 w-3.5" />
                      </button>
                      {/* Mount Custom Video Button on Tile */}
                      <label
                        className="cursor-pointer rounded border border-edge2/70 bg-surface/80 p-1 text-slate-200 hover:border-cyan hover:text-cyan"
                        title="Mount Custom .mp4 Video on this Tile"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Upload className="h-3.5 w-3.5" />
                        <input
                          type="file"
                          accept="video/mp4,video/webm"
                          className="hidden"
                          onChange={(e) => {
                            const file = e.target.files?.[0]
                            if (file) mountCustomVideo(camId, file)
                          }}
                        />
                      </label>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          openForensic(camId)
                        }}
                        className="rounded border border-gold/50 bg-gold/10 p-1 text-gold-soft hover:bg-gold/20"
                        title="Open forensic playback"
                      >
                        <ScanLine className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                  {cam.models.length > 0 && (
                    <div className="flex flex-wrap justify-end gap-1">
                      {cam.models.map((mid) => (
                        <ModelBadge key={mid} id={mid} size="xs" />
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* A3/A9 FIX: Hover overlay only on side tiles — subtle dim, no text */}
              {!isMain && (
                <div className="pointer-events-none absolute inset-0 hidden items-center justify-center bg-black/35 backdrop-blur-[1px] group-hover:flex" />
              )}

              {isDropTarget && (
                <div className="pointer-events-none absolute inset-0 border-2 border-dashed border-gold/70 bg-gold/5" />
              )}
            </div>
          )
        })}
      </div>

      {/* ── Forensic inspection overlay ──────────────────────────────────────── */}
      {forensicCameraId && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          {/*
           * BUG-1 FIX: onClose was calling exitFullscreen() (browser Fullscreen
           * API) which never cleared forensicCameraId — panel was un-closeable.
           * Now correctly calls closeForensic() from AppContext, which sets
           * forensicCameraId to null and dismisses the overlay.
           */}
          <ForensicPanel cameraId={forensicCameraId} onClose={closeForensic} />
        </div>
      )}



    </main>
  )
}
