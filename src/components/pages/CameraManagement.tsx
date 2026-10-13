import { useCallback, useEffect, useState } from 'react'
import {
  Plus,
  Pencil,
  Trash2,
  X,
  Check,
  Upload,
  Video,
  MapPin,
  Cpu,
} from 'lucide-react'
import { useApp } from '../../store/AppContext'
import { AI_MODELS, CAMERA_SOURCE_VIDEOS } from '../../constants'
import type { NewCameraInput } from '../../types'

interface CameraDraft {
  index: string
  name: string
  zone: string
  ip: string
  videoUrl: string
  models: string[]
  x: string
  y: string
}

const BLANK_DRAFT: CameraDraft = {
  index: '',
  name: '',
  zone: '',
  ip: '192.168.27.110',
  videoUrl: CAMERA_SOURCE_VIDEOS[0].url,
  models: [],
  x: '50',
  y: '50',
}

function ipEndsWith(ip: string): boolean {
  const m = ip.match(/^192\.168\.27\.(\d{1,3})$/)
  if (!m) return false
  const n = Number(m[1])
  return n >= 0 && n <= 254
}

export default function CameraManagement() {
  const {
    cameras,
    addCamera,
    deleteCamera,
    updateCameraDetails,
    setCameraModels,
    setCameraVideo,
    canEdit,
  } = useApp()

  const [draft, setDraft] = useState<CameraDraft | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [videoInputKey, setVideoInputKey] = useState(0)

  // keep the draft's index field in sync with reality (prefill next free index)
  useEffect(() => {
    if (!draft) return
    if (draft.index !== '') return
    const next = (cameras.length ? Math.max(...cameras.map((c) => c.index)) : 0) + 1
    setDraft((d) => (d && d.index === '' ? { ...d, index: String(next) } : d))
  }, [cameras, draft])

  const nextIp = useCallback(() => {
    for (let i = 110; i < 255; i++) {
      const ip = `192.168.27.${i}`
      if (!cameras.some((c) => c.ip === ip)) return ip
    }
    return '192.168.27.254'
  }, [cameras])

  const openAdd = () => {
    const next = (cameras.length ? Math.max(...cameras.map((c) => c.index)) : 0) + 1
    setDraft({
      ...BLANK_DRAFT,
      index: String(next),
      ip: nextIp(),
      x: String(Math.round(15 + Math.random() * 70)),
      y: String(Math.round(15 + Math.random() * 65)),
    })
  }

  const openEdit = (camId: string) => {
    const cam = cameras.find((c) => c.id === camId)
    if (!cam) return
    setDraft({
      index: String(cam.index),
      name: cam.name,
      zone: cam.zone,
      ip: cam.ip,
      videoUrl: cam.videoUrl,
      models: [...cam.models],
      x: String(cam.x),
      y: String(cam.y),
    })
  }

  const save = () => {
    if (!draft) return
    const index = parseInt(draft.index, 10)
    if (Number.isNaN(index) || index < 1 || index > 999) return
    if (!ipEndsWith(draft.ip)) return

    patchCameras(index, draft)
    setDraft(null)
  }

  /** Apply add-or-edit atomically against the live store. */
  const patchCameras = (index: number, d: CameraDraft) => {
    const existing = cameras.find((c) => c.index === index)
    if (existing) {
      // edit: name, zone, ip, camera number and models
      updateCameraDetails(existing.id, {
        name: d.name.trim() || existing.name,
        zone: d.zone.trim() || existing.zone,
        ip: d.ip.trim(),
        index,
      })
      setCameraModels(existing.id, d.models)
      // video sync (unless a fresh blob upload is pending)
      if (!d.videoUrl.startsWith('blob:') || d.videoUrl !== existing.videoUrl) {
        setCameraVideo(existing.id, d.videoUrl)
      }
      return
    }
    // add
    const input: NewCameraInput = {
      index,
      name: d.name,
      zone: d.zone,
      ip: d.ip,
      videoUrl: d.videoUrl,
      models: d.models,
      x: Math.min(90, Math.max(5, parseFloat(d.x) || 50)),
      y: Math.min(90, Math.max(5, parseFloat(d.y) || 50)),
    }
    addCamera(input)
  }

  const handleVideoUpload = (file: File) => {
    const url = URL.createObjectURL(file)
    setVideoInputKey((k) => k + 1)
    setDraft((d) => (d ? { ...d, videoUrl: url } : d))
  }

  if (!canEdit) {
    return (
      <main className="flex min-h-0 flex-1 items-center justify-center bg-base p-6">
        <div className="max-w-md rounded-xl border border-danger/40 bg-danger/10 p-8 text-center">
          <div className="mb-2 text-3xl">🔒</div>
          <h1 className="hud-label text-lg text-danger">ADMIN ACCESS REQUIRED</h1>
          <p className="mt-2 text-sm text-slate-300">
            Camera Management is restricted to System Administrators. Switch the
            role in the top bar to manage cameras.
          </p>
        </div>
      </main>
    )
  }

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto bg-base p-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="hud-label text-2xl text-gold-soft">CAMERA MANAGEMENT</h1>
          <span className="rounded border border-cyan/40 bg-cyan/10 px-2 py-0.5 text-[10px] font-bold text-cyan">
            ADMIN ONLY
          </span>
        </div>
        <button onClick={openAdd} className="btn-gold text-xs">
          <Plus className="h-4 w-4" />
          Add Camera
        </button>
      </div>

      <p className="text-xs text-slate-400">
        Changes are applied to a single camera catalogue that powers the Live
        Wall, Tactical Map, AI Models page and incident alerts immediately.
      </p>

      {/* Camera table */}
      <div className="overflow-auto rounded-lg border border-edge/50 bg-surface2/30">
        <table className="w-full text-sm">
          <thead className="sticky top-0 border-b border-edge/50 bg-surface/80">
            <tr className="text-slate-300 text-[11px] font-semibold uppercase tracking-wider">
              <th className="px-3 py-2 text-left">CAM</th>
              <th className="px-3 py-2 text-left">Name</th>
              <th className="px-3 py-2 text-left">Zone</th>
              <th className="px-3 py-2 text-left">IP Address</th>
              <th className="px-3 py-2 text-left">AI Models</th>
              <th className="px-3 py-2 text-left">Stream</th>
              <th className="px-3 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-edge/30">
            {cameras.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-slate-500">
                  No cameras registered. Click “Add Camera” to register the first one.
                </td>
              </tr>
            )}
            {cameras.map((cam) => (
              <tr key={cam.id} className="even:bg-white/[0.02] hover:bg-steel/10 transition">
                <td className="px-3 py-2 font-bold text-gold-soft">CAM {cam.index}</td>
                <td className="px-3 py-2 text-slate-200">{cam.name}</td>
                <td className="px-3 py-2 text-slate-400">{cam.zone}</td>
                <td className="px-3 py-2 font-mono text-[11px] text-cyan">{cam.ip}</td>
                <td className="px-3 py-2">
                  <div className="flex max-w-[280px] flex-wrap gap-1">
                    {cam.models.length === 0 && (
                      <span className="text-[10px] text-slate-600">No models</span>
                    )}
                    {cam.models.map((mid) => (
                      <span
                        key={mid}
                        className="rounded border border-edge2/50 bg-surface2/50 px-1.5 py-px text-[9px] font-semibold text-slate-300"
                      >
                        {mid.toUpperCase()}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2">
                  <span className="inline-flex max-w-[150px] items-center gap-1.5 truncate text-[10px] text-slate-500">
                    <Video className="h-3 w-3 flex-shrink-0" />
                    <span className="truncate">
                      {cam.videoUrl.startsWith('blob:') ? 'local file' : cam.videoUrl}
                    </span>
                  </span>
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center justify-end gap-1.5">
                    <button
                      onClick={() => openEdit(cam.id)}
                      className="btn-icon h-7 w-7"
                      title={`Edit CAM ${cam.index}`}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => setConfirmDelete(cam.id)}
                      className="btn-icon h-7 w-7 text-danger hover:border-danger/60"
                      title={`Delete CAM ${cam.index}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Add / Edit modal */}
      {draft && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="max-h-[92vh] w-full max-w-lg animate-confirm-pop overflow-y-auto rounded-xl border border-edge/60 bg-deep/95 p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="hud-label text-sm font-bold text-gold-soft">
                {cameras.some((c) => c.index === parseInt(draft.index, 10))
                  ? `EDIT CAMERA — CAM ${draft.index}`
                  : `ADD CAMERA — CAM ${draft.index}`}
              </h2>
              <button className="btn-icon" onClick={() => setDraft(null)} title="Close">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[10px] font-semibold text-slate-400">
                    CAMERA NUMBER
                  </label>
                  <input
                    value={draft.index}
                    onChange={(e) =>
                      setDraft((d) => (d ? { ...d, index: e.target.value.replace(/\D/g, '') } : d))
                    }
                    className="w-full rounded-lg border border-edge2/50 bg-surface/60 px-2 py-1.5 text-xs text-slate-200 focus:border-cyan/60 focus:outline-none"
                    inputMode="numeric"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-semibold text-slate-400">IP ADDRESS</label>
                  <input
                    value={draft.ip}
                    onChange={(e) =>
                      setDraft((d) => (d ? { ...d, ip: e.target.value } : d))
                    }
                    className={`w-full rounded-lg border bg-surface/60 px-2 py-1.5 text-xs font-mono focus:outline-none ${
                      ipEndsWith(draft.ip)
                        ? 'border-edge2/50 text-cyan focus:border-cyan/60'
                        : 'border-danger/60 text-danger focus:border-danger'
                    }`}
                    placeholder="192.168.27.x"
                  />
                </div>
              </div>

              <div>
                <label className="text-[10px] font-semibold text-slate-400">CAMERA NAME</label>
                <input
                  value={draft.name}
                  onChange={(e) => setDraft((d) => (d ? { ...d, name: e.target.value } : d))}
                  className="w-full rounded-lg border border-edge2/50 bg-surface/60 px-2 py-1.5 text-xs text-slate-200 focus:border-cyan/60 focus:outline-none"
                  placeholder="e.g. Sector F — Main Gate"
                />
              </div>

              <div>
                <label className="text-[10px] font-semibold text-slate-400">
                  LOCATION / ZONE
                </label>
                <input
                  value={draft.zone}
                  onChange={(e) => setDraft((d) => (d ? { ...d, zone: e.target.value } : d))}
                  className="w-full rounded-lg border border-edge2/50 bg-surface/60 px-2 py-1.5 text-xs text-slate-200 focus:border-cyan/60 focus:outline-none"
                  placeholder="e.g. Block F"
                />
              </div>

              <div>
                <label className="text-[10px] font-semibold text-slate-400">AI MODELS / SPECS</label>
                <div className="mt-1 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                  {AI_MODELS.map((m) => {
                    const active = draft.models.includes(m.id)
                    return (
                      <button
                        key={m.id}
                        onClick={() =>
                          setDraft((d) =>
                            d
                              ? {
                                  ...d,
                                  models: active
                                    ? d.models.filter((x) => x !== m.id)
                                    : [...d.models, m.id],
                                }
                              : d,
                          )
                        }
                        className={`flex items-center gap-1.5 rounded border px-2 py-1 text-[10px] font-semibold transition ${
                          active
                            ? 'border-gold/60 bg-gold/15 text-gold-soft'
                            : 'border-edge2/40 bg-surface/40 text-slate-400 hover:border-edge2/70'
                        }`}
                      >
                        {active ? <Check className="h-3 w-3" /> : <Cpu className="h-3 w-3" />}
                        {m.short}
                      </button>
                    )
                  })}
                </div>
              </div>

              <div>
                <label className="text-[10px] font-semibold text-slate-400">LINKED VIDEO STREAM</label>
                <select
                  value={draft.videoUrl}
                  onChange={(e) => setDraft((d) => (d ? { ...d, videoUrl: e.target.value } : d))}
                  className="mt-1 w-full rounded-lg border border-edge2/50 bg-surface/60 px-2 py-1.5 text-xs text-slate-200 focus:border-cyan/60 focus:outline-none"
                >
                  {CAMERA_SOURCE_VIDEOS.map((v: any) => (
                    <option key={v.url} value={v.url}>
                      {v.label} — {v.url}
                    </option>
                  ))}
                </select>
                <div className="mt-1.5 flex items-center gap-2">
                  <button
                    onClick={() => document.getElementById('camera-video-input')?.click()}
                    className="btn gap-2 text-xs flex-1"
                  >
                    <Upload className="h-3.5 w-3.5" />
                    {draft.videoUrl.startsWith('blob:') ? 'Replace upload' : 'Upload .mp4'}
                  </button>
                  <span className="truncate text-[9px] text-cyan max-w-[140px]">
                    {draft.videoUrl.startsWith('blob:') ? 'local file' : 'built-in clip'}
                  </span>
                </div>
                <input
                  id="camera-video-input"
                  key={videoInputKey}
                  type="file"
                  accept="video/mp4"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) handleVideoUpload(f)
                  }}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="flex items-center gap-1 text-[10px] font-semibold text-slate-400">
                    <MapPin className="h-3 w-3" />
                    MAP X (0–100)
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={draft.x}
                    onChange={(e) => setDraft((d) => (d ? { ...d, x: e.target.value } : d))}
                    className="w-full rounded-lg border border-edge2/50 bg-surface/60 px-2 py-1.5 text-xs text-slate-200 focus:border-cyan/60 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="flex items-center gap-1 text-[10px] font-semibold text-slate-400">
                    <MapPin className="h-3 w-3" />
                    MAP Y (0–100)
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={draft.y}
                    onChange={(e) => setDraft((d) => (d ? { ...d, y: e.target.value } : d))}
                    className="w-full rounded-lg border border-edge2/50 bg-surface/60 px-2 py-1.5 text-xs text-slate-200 focus:border-cyan/60 focus:outline-none"
                  />
                </div>
              </div>

              <div className="flex items-center justify-between border-t border-edge/40 pt-3">
                <button
                  onClick={() => setDraft(null)}
                  className="btn text-xs gap-2 text-danger border-danger/40 hover:border-danger/70"
                >
                  <X className="h-3.5 w-3.5" />
                  Cancel
                </button>
                <button
                  onClick={save}
                  disabled={!draft.name.trim() || !ipEndsWith(draft.ip) || !draft.index}
                  className="btn-gold text-xs disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Check className="h-3.5 w-3.5" />
                  Save Camera
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="w-full max-w-sm animate-confirm-pop rounded-xl border border-danger/50 bg-deep/95 p-5 shadow-2xl">
            <h2 className="hud-label text-sm font-bold text-danger">DELETE CAMERA</h2>
            {cameras
              .filter((c) => c.id === confirmDelete)
              .map((cam) => (
                <p key={cam.id} className="mt-2 text-xs text-slate-300">
                  Remove <span className="font-bold text-gold-soft">CAM {cam.index}</span> —{' '}
                  {cam.name}? This removes it from the Live Wall, Tactical Map and all
                  camera lists immediately. Historical incidents are retained.
                </p>
              ))}
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setConfirmDelete(null)} className="btn text-xs">
                Cancel
              </button>
              <button
                onClick={() => {
                  deleteCamera(confirmDelete)
                  setConfirmDelete(null)
                }}
                className="btn text-xs gap-2 border-danger/50 text-danger hover:border-danger hover:bg-danger/10"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Delete Camera
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
