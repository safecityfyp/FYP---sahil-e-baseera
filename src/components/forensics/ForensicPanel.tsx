import { useCallback, useEffect, useRef, useState } from 'react'
import { X, Play, Pause } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import { SEVERITY_META } from '../../constants'
import ModelBadge from '../ui/ModelBadge'
import { fmtStampShort } from '../../lib/format'

interface ForensicPanelProps {
  cameraId: string
  onClose: () => void
}

/**
 * Forensic single-stream inspection: timeline scrubber with visual markers at
 * every ClipEvent timestamp, hover tooltip (event name, confidence) and
 * click-to-seek. Playback is intentionally NOT looped here so an operator can
 * scrub back to an event after it passed.
 */
export default function ForensicPanel({ cameraId, onClose }: ForensicPanelProps) {
  const { cameras, speed, setSpeed, incidents } = useApp()
  const cam = cameras.find((c) => c.id === cameraId)

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [hoverEvent, setHoverEvent] = useState<{ time: number; x: number } | null>(null)

  useEffect(() => {
    const el = videoRef.current
    if (!el) return
    const onTime = () => setCurrentTime(el.currentTime)
    const onLoaded = () => setDuration(el.duration || 0)
    const onEnded = () => setPlaying(false)
    el.addEventListener('timeupdate', onTime)
    el.addEventListener('loadedmetadata', onLoaded)
    el.addEventListener('ended', onEnded)
    return () => {
      el.removeEventListener('timeupdate', onTime)
      el.removeEventListener('loadedmetadata', onLoaded)
      el.removeEventListener('ended', onEnded)
    }
  }, [cameraId])

  useEffect(() => {
    const el = videoRef.current
    if (!el) return
    el.playbackRate = speed
  }, [speed, cameraId])

  const seekTo = useCallback((time: number) => {
    const el = videoRef.current
    if (el) {
      el.currentTime = time
      setCurrentTime(time)
      setPlaying(true)
      void el.play().catch(() => {})
    }
  }, [])

  const togglePlay = useCallback(() => {
    const el = videoRef.current
    if (!el) return
    if (el.paused) {
      void el.play().catch(() => {})
      setPlaying(true)
    } else {
      el.pause()
      setPlaying(false)
    }
  }, [])

  if (!cam) return null

  const durationSec = duration || cam.duration
  const sortedEvents = [...cam.events].sort((a, b) => a.time - b.time)

  // incidents for THIS camera (real, from the shared persisted store)
  const camIncidents = incidents
    .filter((i) => i.cameraId === cam.id)
    .sort((a, b) => a.firedAt - b.firedAt)

  const pct = (t: number) => Math.min(100, Math.max(0, (t / Math.max(durationSec, 1)) * 100))

  return (
    <div className="w-full max-w-4xl animate-confirm-pop rounded-xl border border-edge/60 bg-deep/95 shadow-2xl backdrop-blur-xl">
      {/* Header */}
      <div className="flex items-center justify-between rounded-t-xl border-b border-edge/60 bg-surface2/60 px-5 py-3">
        <div>
          <div className="hud-label text-sm font-bold text-gold-soft">
            FORENSIC INSPECTION — CAM {cam.index}
          </div>
          <div className="text-[11px] text-slate-400">
            {cam.name} · {cam.ip}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded border border-cyan/40 bg-cyan/10 px-2 py-0.5 text-[10px] font-bold text-cyan">
            LIVE EVENT TIMESTAMPS
          </span>
          <button onClick={onClose} className="btn-icon" title="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Video + timeline */}
      <div className="space-y-4 p-5">
        {/* Video stage */}
        <div className="relative overflow-hidden rounded-lg border border-edge/60 bg-black">
          <video
            ref={videoRef}
            key={`forensic-${cam.id}`}
            src={cam.videoUrl}
            className="h-full w-full max-h-[32vh] object-contain bg-black"
            autoPlay
            muted
            playsInline
          />
          <div className="absolute left-2 top-2 flex items-center gap-2">
            <span className="hud-label rounded bg-surface/80 px-2 py-0.5 text-[10px] font-bold text-gold-soft">
              CAM {cam.index}
            </span>
            <span className="rounded bg-danger/80 px-2 py-0.5 text-[10px] font-bold text-white animate-live-blink">
              INSPECTION
            </span>
          </div>
          {/* Scanlines */}
          <div className="scanlines pointer-events-none absolute inset-0" />
        </div>

        {/* Transport controls */}
        <div className="flex items-center gap-3">
          <button onClick={togglePlay} className="btn-icon" title={playing ? 'Pause' : 'Play'}>
            {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </button>
          <span className="font-mono text-xs text-cyan">
            {fmtStampShort(currentTime * 1000)} / {fmtStampShort(durationSec * 1000)}
          </span>
          <div className="h-5 w-px bg-edge2/50" />
          <span className="text-xs text-slate-400 font-semibold">SPEED:</span>
          <select
            value={speed}
            onChange={(e) => setSpeed(parseFloat(e.target.value))}
            className="btn text-xs"
          >
            <option value={1}>1×</option>
            <option value={2}>2×</option>
          </select>
          <div className="flex-1" />
          <span className="text-[10px] text-slate-500">
            {sortedEvents.length} event{sortedEvents.length === 1 ? '' : 's'} on this clip
          </span>
        </div>

        {/* Timeline scrubber with event markers */}
        <div className="relative">
          {/* track */}
          <input
            type="range"
            min={0}
            max={Math.max(durationSec, 1)}
            step={0.05}
            value={currentTime}
            onChange={(e) => seekTo(parseFloat(e.target.value))}
            className="w-full accent-cyan cursor-pointer"
            aria-label="Timeline scrubber"
          />

          {/* event marker flags */}
          <div className="pointer-events-none relative mt-2 h-5">
            {sortedEvents.map((ev) => {
              const sev = SEVERITY_META[ev.modelId === 'helmet' ? 'low' : 'medium']
              const color = ev.modelId === 'weapon' || ev.modelId === 'fire' || ev.modelId === 'accident' || ev.modelId === 'abandoned'
                ? '#EF4444'
                : sev.color
              const left = pct(ev.time)
              return (
                <button
                  key={`m-${ev.time}-${ev.modelId}`}
                  className="pointer-events-auto absolute top-0 h-5 w-2 -translate-x-1/2 rounded-sm"
                  style={{ left: `${left}%`, backgroundColor: color }}
                  title={`${ev.title} @ ${fmtStampShort(ev.time * 1000)}`}
                  onClick={() => seekTo(ev.time)}
                  onMouseEnter={(e) =>
                    setHoverEvent({ time: ev.time, x: e.currentTarget.getBoundingClientRect().left })
                  }
                  onMouseLeave={() => setHoverEvent(null)}
                />
              )
            })}

            {/* hover tooltip */}
            {hoverEvent && (() => {
              const ev = cam.events.find((e) => e.time === hoverEvent.time)
              if (!ev) return null
              const sevColor =
                ev.modelId === 'weapon' || ev.modelId === 'fire' || ev.modelId === 'accident' || ev.modelId === 'abandoned'
                  ? '#EF4444'
                  : SEVERITY_META[ev.modelId === 'helmet' ? 'low' : 'medium'].color
              return (
                <div
                  className="pointer-events-none absolute -top-16 z-10 w-52 -translate-x-1/2 rounded-lg border bg-surface/95 p-2.5 shadow-xl backdrop-blur-xl"
                  style={{ left: `${pct(ev.time)}%`, borderColor: sevColor }}
                >
                  <div className="text-[11px] font-bold" style={{ color: sevColor }}>
                    {ev.title}
                  </div>
                  <div className="mt-0.5 text-[10px] text-slate-400">{ev.detail}</div>
                  <div className="mt-1 flex items-center justify-between text-[10px]">
                    <span className="font-mono text-cyan">@{fmtStampShort(ev.time * 1000)}</span>
                    <span className="font-bold text-warn">{ev.confidence}%</span>
                  </div>
                  {ev.plate && <div className="text-[10px] text-slate-300 mt-0.5">Plate: {ev.plate}</div>}
                </div>
              )
            })()}
          </div>
        </div>

        {/* Event list */}
        <div className="rounded-lg border border-edge/50 bg-surface2/30 p-3">
          <div className="hud-label mb-2 text-[10px] text-slate-400">CLICK MARKER TO SEEK</div>
          <div className="grid grid-cols-2 gap-2">
            {sortedEvents.map((ev) => {
              const isHigh =
                ev.modelId === 'weapon' || ev.modelId === 'fire' || ev.modelId === 'accident' || ev.modelId === 'abandoned'
              const color = isHigh ? '#EF4444' : SEVERITY_META[ev.modelId === 'helmet' ? 'low' : 'medium'].color
              return (
                <button
                  key={`l-${ev.time}`}
                  onClick={() => seekTo(ev.time)}
                  className="flex items-center justify-between rounded border px-2 py-1.5 text-left transition hover:opacity-80"
                  style={{ borderColor: `${color}66`, backgroundColor: `${color}12` }}
                >
                  <div className="min-w-0">
                    <div className="truncate text-[11px] font-bold" style={{ color }}>
                      {ev.title}
                    </div>
                    <div className="flex items-center gap-2 text-[9px] text-slate-400">
                      <ModelBadge id={ev.modelId} size="xs" />
                      <span className="font-mono">@{fmtStampShort(ev.time * 1000)}</span>
                    </div>
                  </div>
                  <span className="ml-2 flex-shrink-0 font-mono text-[10px] text-warn">
                    {ev.confidence}%
                  </span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Related real incidents for this camera */}
        {camIncidents.length > 0 && (
          <div className="rounded-lg border border-edge/50 bg-surface2/30 p-3">
            <div className="hud-label mb-2 text-[10px] text-slate-400">
              HISTORICAL INCIDENTS — THIS CAMERA (FROM PERSISTED LOG)
            </div>
            <div className="max-h-28 overflow-y-auto space-y-1">
              {camIncidents.map((inc) => (
                <div
                  key={inc.id}
                  className="flex items-center justify-between rounded border border-edge/40 bg-surface/40 px-2 py-1 text-[10px]"
                >
                  <span className="text-slate-300">{inc.event}</span>
                  <span className="flex items-center gap-2">
                    <span style={{ color: SEVERITY_META[inc.severity].color }} className="font-bold">
                      {SEVERITY_META[inc.severity].label}
                    </span>
                    <span className="font-mono text-slate-500">
                      {new Date(inc.firedAt).toLocaleString('en-GB', { hour12: false })}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
