import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type {
  HardwareTelemetry,
  ThemeMode,
  AiModel,
  Camera,
  ClipEvent,
  Incident,
  LayoutId,
  NewCameraInput,
  ReportPeriod,
  Role,
  Severity,
  TabId,
  Toast,
} from '../types'
import { AI_MODELS, CAMERAS, INITIAL_HARDWARE_SPECS, STORAGE_KEYS } from '../constants'
import {
  loadCameraCatalogue,
  loadCameraVideoUrls,
  loadCameraSequence,
  loadFiredKeys,
  loadIncidents,
  loadSeverityOverrides,
  saveCameraCatalogue,
  saveCameraSequence,
  saveCameraVideoUrl,
  saveFiredKeys,
  saveIncidents,
  saveSeverityOverrides,
} from '../lib/storage'
import { blip, playSiren, stopSiren, unlockAudio } from '../lib/audio'

/**
 * A lightweight pending entry for events that fired on a side (non-main)
 * tile. These stay SILENT — no popup, no toast, no siren — until the camera
 * is moved into the main tile, at which point they are announced once.
 * (Item 5: alerts scoped to the main/focused camera only.)
 */
export interface ActivityEntry {
  id: string
  /** real incident id so announcements can ack the backing record */
  incidentId: string
  firedAt: number
  cameraId: string
  cameraIndex: number
  cameraName: string
  zone: string
  event: string
  severity: Severity
  announced: boolean
}

interface AppState {
  // clock
  now: number

  // rbac
  role: Role
  setRole: (r: Role) => void
  canEdit: boolean

  // theme
  theme: ThemeMode
  setTheme: (t: ThemeMode) => void
  toggleTheme: () => void

  // hardware telemetry
  hardware: HardwareTelemetry

  // navigation
  tab: TabId
  setTab: (t: TabId) => void
  sidebarCollapsed: boolean
  setSidebarCollapsed: (v: boolean) => void
  toggleSidebar: () => void

  // cameras
  cameras: Camera[]
  getCamera: (id: string | null) => Camera | undefined
  setCameraVideo: (id: string, url: string) => void
  moveCamera: (id: string, x: number, y: number) => void
  updateCameraDetails: (
    id: string,
    patch: Partial<Pick<Camera, 'name' | 'ip' | 'zone' | 'index'>>,
  ) => void
  setCameraModels: (id: string, modelIds: string[]) => void
  toggleCameraModel: (id: string, modelId: string) => void
  addCamera: (input: NewCameraInput) => string
  deleteCamera: (id: string) => void
  mountCustomVideo: (cameraId: string, file: File) => void

  // models & severity
  models: AiModel[]
  severityOverrides: Record<string, Severity>
  setSeverity: (modelId: string, sev: Severity) => void
  severityOf: (modelId: string) => Severity

  // live wall
  layout: LayoutId
  setLayout: (l: LayoutId) => void
  order: string[] // camera ids in display order; order[0] = main
  focusCamera: (id: string) => void
  swapTiles: (fromIndex: number, toIndex: number) => void
  mainId: string
  playing: boolean
  setPlaying: (v: boolean) => void
  speed: number
  setSpeed: (s: number) => void

  // forensic playback panel (rendered globally so it works from any tab)
  forensicCameraId: string | null
  openForensic: (id: string) => void
  closeForensic: () => void

  // alerts
  incidents: Incident[]
  toasts: Toast[]
  dismissToast: (id: string) => void
  criticalAlert: Incident | null
  acknowledgeAlert: () => void
  soundEnabled: boolean
  setSoundEnabled: (v: boolean) => void
  resetSimulation: () => void

  // silent pending queue for side-tile events (internal — not rendered)
  activityFeed: ActivityEntry[]
  dismissFeedEntry: (id: string) => void
  acknowledgeIncident: (id: string) => void

  // reporting period — shared by Analytics, Incident Log and PDF export
  reportPeriod: ReportPeriod
  setReportPeriod: (p: ReportPeriod) => void
  customRange: { from: number; to: number } | null
  setCustomRange: (r: { from: number; to: number } | null) => void
}

const AppContext = createContext<AppState | null>(null)

/** Reconstruct the camera catalogue from persisted state, if any. */
function hydrateCameras(): Camera[] {
  const catalogue = loadCameraCatalogue()
  if (catalogue) return catalogue
  const overrides = loadCameraVideoUrls()
  return CAMERAS.map((c) => {
    const url = overrides[c.id]
    if (!url) return c
    return { ...c, videoUrl: url }
  })
}

/**
 * When a new camera is bound to one of the built-in inference clips, reuse
 * the clip's known ClipEvents (filtered to the assigned models) so the new
 * camera can participate in live alert generation immediately.
 */
function eventsForVideo(url: string, models: string[]): ClipEvent[] {
  const src = CAMERAS.find((c) => c.videoUrl === url)
  if (!src) return []
  return src.events.filter((ev) => models.includes(ev.modelId))
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [now, setNow] = useState(Date.now())
  const [role, setRole] = useState<Role>('super-admin')
  const [tab, setTab] = useState<TabId>('wall')
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('safecity.sidebarCollapsed.v2') === 'true'
    } catch {
      return false
    }
  })

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem('safecity.sidebarCollapsed.v2', String(next))
      } catch {}
      return next
    })
  }, [])

  const [theme, setThemeState] = useState<ThemeMode>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.theme)
      return saved === 'light' ? 'light' : 'dark'
    } catch {
      return 'dark'
    }
  })

  const [hardware, setHardware] = useState<HardwareTelemetry>(INITIAL_HARDWARE_SPECS)

  const setTheme = useCallback((newTheme: ThemeMode) => {
    setThemeState(newTheme)
    try {
      localStorage.setItem(STORAGE_KEYS.theme, newTheme)
    } catch {}
  }, [])

  const toggleTheme = useCallback(() => {
    setTheme(theme === 'dark' ? 'light' : 'dark')
  }, [theme, setTheme])

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'light') {
      root.classList.add('light')
      root.classList.remove('dark')
    } else {
      root.classList.add('dark')
      root.classList.remove('light')
    }
  }, [theme])

  // Periodic simulated live hardware jitter
  useEffect(() => {
    const timer = window.setInterval(() => {
      setHardware((prev) => {
        const cpuJitter = Math.min(95, Math.max(12, prev.cpu.percent + (Math.random() * 6 - 3)))
        const gpuJitter = Math.min(98, Math.max(30, prev.gpu.utilPercent + (Math.random() * 8 - 4)))
        const vramJitter = Math.min(4096, Math.max(2800, Math.round(prev.gpu.vramUsedMb + (Math.random() * 60 - 30))))
        const ramJitter = Math.min(32, Math.max(14, +(prev.ram.usedGb + (Math.random() * 0.4 - 0.2)).toFixed(1)))
        const ramPct = Math.round((ramJitter / prev.ram.totalGb) * 100)
        const fpsJitter = +(58.2 + (Math.random() * 2.4 - 1.2)).toFixed(1)

        return {
          ...prev,
          cpu: { ...prev.cpu, percent: +cpuJitter.toFixed(1) },
          gpu: { ...prev.gpu, utilPercent: +gpuJitter.toFixed(1), vramUsedMb: vramJitter },
          ram: { ...prev.ram, usedGb: ramJitter, percent: ramPct },
          fps: fpsJitter,
        }
      })
    }, 2500)
    return () => window.clearInterval(timer)
  }, [])

  const mountCustomVideo = useCallback((cameraId: string, file: File) => {
    const url = URL.createObjectURL(file)
    setCameras((prev) =>
      prev.map((c) => (c.id === cameraId ? { ...c, videoUrl: url, customVideo: true } : c)),
    )
  }, [])

  // cameras hydrate from the persisted catalogue (admin CRUD), else defaults
  const [cameras, setCameras] = useState<Camera[]>(() => hydrateCameras())
  const [severityOverrides, setSeverityOverrides] = useState<Record<string, Severity>>(
    () => loadSeverityOverrides(),
  )

  const [layout, setLayout] = useState<LayoutId>('focus')
  const [order, setOrder] = useState<string[]>(() => {
    const catalogue = loadCameraCatalogue()
    return (catalogue ?? CAMERAS).map((c) => c.id)
  })
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(1)

  const [incidents, setIncidents] = useState<Incident[]>(() => loadIncidents())
  const [toasts, setToasts] = useState<Toast[]>([])
  const [criticalAlert, setCriticalAlert] = useState<Incident | null>(null)
  const [soundEnabled, setSoundEnabled] = useState(true)

  // Silent pending queue for side-tile events (never rendered as a popup).
  const [activityFeed, setActivityFeed] = useState<ActivityEntry[]>([])

  const [forensicCameraId, setForensicCameraId] = useState<string | null>(null)

  const [reportPeriod, setReportPeriod] = useState<ReportPeriod>('today')
  const [customRange, setCustomRange] = useState<{ from: number; to: number } | null>(null)

  const canEdit = role === 'super-admin'

  // ---- wall clock ---------------------------------------------------------
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])

  // ---- audio unlock on first user interaction -----------------------------
  useEffect(() => {
    const unlock = () => {
      unlockAudio()
      window.removeEventListener('click', unlock, true)
      window.removeEventListener('keydown', unlock, true)
    }
    window.addEventListener('click', unlock, true)
    window.addEventListener('keydown', unlock, true)
    return () => {
      window.removeEventListener('click', unlock, true)
      window.removeEventListener('keydown', unlock, true)
    }
  }, [])

  // ---- A2: play/pause propagation to all mounted video elements -----------
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

  // ---- persistence --------------------------------------------------------
  useEffect(() => {
    saveIncidents(incidents)
  }, [incidents])

  useEffect(() => {
    saveSeverityOverrides(severityOverrides)
  }, [severityOverrides])

  useEffect(() => {
    saveCameraCatalogue(cameras)
  }, [cameras])

  // ---- helpers ------------------------------------------------------------
  const getCamera = useCallback(
    (id: string | null) => cameras.find((c) => c.id === id),
    [cameras],
  )

  const severityOf = useCallback(
    (modelId: string): Severity => {
      if (severityOverrides[modelId]) return severityOverrides[modelId]
      return AI_MODELS.find((m) => m.id === modelId)?.severity ?? 'low'
    },
    [severityOverrides],
  )

  const setSeverity = useCallback((modelId: string, sev: Severity) => {
    setSeverityOverrides((prev) => ({ ...prev, [modelId]: sev }))
  }, [])

  const models = useMemo<AiModel[]>(
    () => AI_MODELS.map((m) => ({ ...m, severity: severityOverrides[m.id] ?? m.severity })),
    [severityOverrides],
  )

  const setCameraVideo = useCallback((id: string, url: string) => {
    setCameras((prev) =>
      prev.map((c) =>
        c.id === id
          ? { ...c, videoUrl: url, customVideo: url.startsWith('blob:') }
          : c,
      ),
    )
    // only persist non-blob URLs (blob object URLs expire with the session)
    if (!url.startsWith('blob:')) saveCameraVideoUrl(id, url)
  }, [])

  const moveCamera = useCallback((id: string, x: number, y: number) => {
    setCameras((prev) => prev.map((c) => (c.id === id ? { ...c, x, y } : c)))
  }, [])

  const updateCameraDetails = useCallback(
    (id: string, patch: Partial<Pick<Camera, 'name' | 'ip' | 'zone' | 'index'>>) => {
      setCameras((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)))
    },
    [],
  )

  const setCameraModels = useCallback((id: string, modelIds: string[]) => {
    setCameras((prev) => prev.map((c) => (c.id === id ? { ...c, models: modelIds } : c)))
  }, [])

  const toggleCameraModel = useCallback((id: string, modelId: string) => {
    setCameras((prev) =>
      prev.map((c) => {
        if (c.id !== id) return c
        const has = c.models.includes(modelId)
        return { ...c, models: has ? c.models.filter((m) => m !== modelId) : [...c.models, modelId] }
      }),
    )
  }, [])

  // ---- camera CRUD (admin-only page) --------------------------------------
  const sequenceRef = useRef(loadCameraSequence())

  const addCamera = useCallback((input: NewCameraInput): string => {
    const seq = sequenceRef.current + 1
    sequenceRef.current = seq
    saveCameraSequence(seq)
    const index = input.index ?? seq
    const id = `CAM-${String(index).padStart(2, '0')}`
    const cam: Camera = {
      id,
      index,
      name: input.name.trim() || `New Camera ${index}`,
      zone: input.zone.trim() || 'Unassigned Zone',
      ip: input.ip.trim() || '192.168.27.0',
      videoUrl: input.videoUrl,
      duration: 12,
      models: [...input.models],
      events: eventsForVideo(input.videoUrl, input.models),
      x: input.x,
      y: input.y,
      customVideo: input.videoUrl.startsWith('blob:'),
    }
    setCameras((prev) => [...prev, cam])
    setOrder((prev) => [...prev, id])
    return id
  }, [])

  const deleteCamera = useCallback((id: string) => {
    setCameras((prev) => prev.filter((c) => c.id !== id))
    setOrder((prev) => {
      const next = prev.filter((x) => x !== id)
      return next.length > 0 ? next : []
    })
    // drop any silent pending entries for the removed camera
    setActivityFeed((prev) => prev.filter((e) => e.cameraId !== id))
    setCriticalAlert((cur) => (cur && cur.cameraId === id ? null : cur))
  }, [])

  // ---- live wall ordering -------------------------------------------------
  const mainId = order[0]
  const mainIdRef = useRef(mainId)
  useEffect(() => {
    mainIdRef.current = mainId
  }, [mainId])

  const focusCamera = useCallback((id: string) => {
    setOrder((prev) => {
      const idx = prev.indexOf(id)
      if (idx <= 0) return prev
      const next = [...prev]
      // swap main (0) with clicked position
      const tmp = next[0]
      next[0] = next[idx]
      next[idx] = tmp
      return next
    })
  }, [])

  /**
   * Drag-and-drop tile swap: swaps the cameras at two display slots. Unlike
   * focusCamera this works between any two slots and never remounts the video
   * elements (tiles stay keyed by camera id).
   */
  const swapTiles = useCallback((fromIndex: number, toIndex: number) => {
    setOrder((prev) => {
      if (fromIndex === toIndex) return prev
      if (fromIndex < 0 || toIndex < 0 || fromIndex >= prev.length || toIndex >= prev.length) {
        return prev
      }
      const next = [...prev]
      ;[next[fromIndex], next[toIndex]] = [next[toIndex], next[fromIndex]]
      return next
    })
  }, [])

  // ---- forensic playback --------------------------------------------------
  const openForensic = useCallback((id: string) => {
    setForensicCameraId(id)
  }, [])
  const closeForensic = useCallback(() => {
    setForensicCameraId(null)
  }, [])

  // ---- alert engine -------------------------------------------------------

  // A4: fire-once-per-session dedupe. Key = camId:modelId:time.
  const firedKeysRef = useRef<Set<string>>(new Set(loadFiredKeys()))
  const firedKeys = firedKeysRef.current // stable reference — always the same Set

  // A5: Per-event-instance announcement tracking (camId:modelId:clipTime).
  // An event is "announced" once it has fired a visible alert/toast/siren.
  const announcedKeysRef = useRef<Set<string>>(new Set())

  const camerasRef = useRef(cameras)
  const severityRef = useRef(severityOf)
  const playingRef = useRef(playing)
  const incidentsRef = useRef(incidents)
  useEffect(() => { camerasRef.current = cameras }, [cameras])
  useEffect(() => { severityRef.current = severityOf }, [severityOf])
  useEffect(() => { playingRef.current = playing }, [playing])
  useEffect(() => { incidentsRef.current = incidents }, [incidents])

  const pushIncident = useCallback((inc: Incident) => {
    setIncidents((prev) => {
      // hard dedupe: a given incident id appears at most once in the log
      if (prev.some((i) => i.id === inc.id)) return prev
      return [inc, ...prev].slice(0, 2000)
    })
  }, [])

  const dismissFeedEntry = useCallback((id: string) => {
    setActivityFeed((prev) => prev.filter((e) => e.id !== id))
  }, [])

  /**
   * Item 5 — main-camera scoping:
   *  - Camera in MAIN tile → high = critical alert + siren, medium = toast,
   *    low = silent log.
   *  - Camera in a SIDE tile → incident is logged to the shared store and a
   *    silent pending entry is queued. NOTHING visible happens. When that
   *    camera becomes main, the pending entry announces itself once.
   */
  const fireEvent = useCallback(
    (cam: Camera, ev: Camera['events'][number], clipKey: string) => {
      const sev = severityRef.current(ev.modelId)
      const at = Date.now()
      const clockLabel = new Date(at).toLocaleString('en-GB', { hour12: false })
      const inc: Incident = {
        id: `${cam.id}-${ev.modelId}-${at}`,
        firedAt: at,
        clockLabel,
        cameraId: cam.id,
        cameraIndex: cam.index,
        cameraName: cam.name,
        zone: cam.zone,
        ip: cam.ip,
        modelId: ev.modelId,
        event: ev.title,
        detail: ev.detail,
        severity: sev,
        confidence: ev.confidence,
        plate: ev.plate,
        vehicle: ev.vehicle,
        speed: ev.speed,
        acknowledged: false,
        dispatched: false,
      }

      // Always log to the shared incident store (single source of truth).
      pushIncident(inc)

      if (sev === 'high') {
        // Critical: always announce immediately regardless of tile position
        setCriticalAlert((cur) => cur ?? inc)
        focusCamera(cam.id)
        // Audio is handled by the useEffect watching criticalAlert below
      } else {
        // Non-critical (medium/low): route based on tile position
        const isMainCam = cam.id === mainIdRef.current
        const announceKey = clipKey // reuse the same key structure

        if (isMainCam) {
          // Main tile: announce once, then mark announced
          if (!announcedKeysRef.current.has(announceKey)) {
            announcedKeysRef.current.add(announceKey)
            if (sev === 'medium') {
              blip()
              const toast: Toast = {
                id: `t-${inc.id}`,
                incidentId: inc.id,
                title: inc.event,
                detail: inc.detail,
                cameraLabel: `CAM ${cam.index} · ${cam.zone}`,
                severity: sev,
              }
              setToasts((prev) => [...prev.slice(-2), toast])
              window.setTimeout(() => {
                setToasts((prev) => prev.filter((t) => t.id !== toast.id))
              }, 12000)
            }
            // low severity on main = silent log (already done via pushIncident)
          }
        } else {
          // Side tile: add to persistent activity feed only — no toast, no blip
          const entry: ActivityEntry = {
            id: `feed-${inc.id}`,
            incidentId: inc.id,
            firedAt: at,
            cameraId: cam.id,
            cameraIndex: cam.index,
            cameraName: cam.name,
            zone: cam.zone,
            event: ev.title,
            severity: sev,
            announced: false,
          }
          setActivityFeed((prev) => [entry, ...prev].slice(0, 50))
        }
      }
    },
    [focusCamera, pushIncident],
  )

  // Poll bound video elements and match against clip event times
  useEffect(() => {
    const interval = window.setInterval(() => {
      if (!playingRef.current) return
      const els = document.querySelectorAll<HTMLVideoElement>('video[data-cam]')
      els.forEach((el) => {
        const camId = el.getAttribute('data-cam')
        if (!camId) return
        const cam = camerasRef.current.find((c) => c.id === camId)
        if (!cam) return
        const ct = el.currentTime
        for (const ev of cam.events) {
          if (Math.abs(ct - ev.time) <= 0.35) {
            const key = `${cam.id}:${ev.modelId}:${ev.time}`
            if (firedKeys.has(key)) continue
            firedKeys.add(key)
            saveFiredKeys(Array.from(firedKeys))
            fireEvent(cam, ev, key)
          }
        }
      })
    }, 250)
    return () => window.clearInterval(interval)
  }, [fireEvent])

  /**
   * Item 5 — when the main camera changes (click/drag/swap), announce any
   * silent entries that belong to the newly focused camera, exactly once.
   * Edge cases: camera swapped into main mid-event, multiple side cameras
   * queued simultaneously — each is announced on its own focus.
   */
  useEffect(() => {
    setActivityFeed((prev) => {
      const unannounced = prev.filter(
        (e) => e.cameraId === mainId && !e.announced,
      )
      if (unannounced.length === 0) return prev

      const liveIncidents = incidentsRef.current
      unannounced.forEach((e) => {
        if (announcedKeysRef.current.has(e.id)) return
        announcedKeysRef.current.add(e.id)
        const inc = liveIncidents.find((i) => i.id === e.incidentId)
        if (e.severity === 'high') {
          setCriticalAlert((cur) => cur ?? inc ?? null)
        } else if (e.severity === 'medium') {
          blip()
          const toast: Toast = {
            id: `t-announce-${e.id}`,
            incidentId: e.incidentId,
            title: e.event,
            detail: inc?.detail ?? `${e.cameraName} — ${e.zone}`,
            cameraLabel: `CAM ${e.cameraIndex} · ${e.zone}`,
            severity: e.severity,
          }
          setToasts((prev) => [...prev.slice(-2), toast])
          window.setTimeout(() => {
            setToasts((tp) => tp.filter((t) => t.id !== toast.id))
          }, 12000)
        }
        // low severity on focus = silent log (already logged)
      })

      return prev.map((e) =>
        e.cameraId === mainId && !e.announced ? { ...e, announced: true } : e,
      )
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mainId])

  // ---- alert controls -----------------------------------------------------
  const acknowledgeAlert = useCallback(() => {
    setCriticalAlert((cur) => {
      if (cur) {
        setIncidents((prev) =>
          prev.map((i) => (i.id === cur.id ? { ...i, acknowledged: true } : i)),
        )
      }
      return null
    })
    stopSiren()
  }, [])

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const acknowledgeIncident = useCallback((incidentId: string) => {
    setIncidents((prev) =>
      prev.map((i) => (i.id === incidentId ? { ...i, acknowledged: true } : i)),
    )
    // Also remove from silent pending queue if present (feed id = 'feed-' + id)
    setActivityFeed((prev) => prev.filter((e) => e.id !== `feed-${incidentId}`))
  }, [])

  /**
   * A4: Admin-only reset. Mutates the existing firedKeys Set in place so the
   * stable reference used by the polling interval reflects the reset. Incident
   * history (analytics) is preserved; only live session state clears.
   */
  const resetSimulation = useCallback(() => {
    firedKeys.clear()
    saveFiredKeys([])
    announcedKeysRef.current.clear()
    setCriticalAlert(null)
    setToasts([])
    setActivityFeed([])
    setIncidents([])
    stopSiren()
  }, [firedKeys])

  // Continuous simulated live surveillance alerts loop when on 'wall' tab
  const scenarioIndexRef = useRef(0)
  useEffect(() => {
    if (tab !== 'wall' || !playing) return

    const LIVE_SCENARIOS = [
      // Critical (High Severity -> Popup alert + Siren beeping on Live Wall)
      {
        modelId: 'accident',
        severity: 'high' as const,
        event: 'Road Accident / Crash Collision',
        detail: 'High-energy vehicle collision flagged at Sector C cross-junction',
        camId: 'CAM-04',
        confidence: 96.4,
        vehicle: 'Toyota Corolla vs Suzuki Alto',
        speed: 52,
      },
      // Non-critical (Medium Severity -> Bottom Right Toast Notification)
      {
        modelId: 'helmet',
        severity: 'medium' as const,
        event: 'Helmet Violation Flagged',
        detail: 'Motorcyclist without certified safety helmet passing checkpoint gate',
        camId: 'CAM-05',
        confidence: 95.7,
        plate: 'RWP-9918',
        vehicle: 'Honda CD-70 (Red)',
      },
      // Non-critical (Medium Severity -> Bottom Right Toast Notification)
      {
        modelId: 'speed',
        severity: 'medium' as const,
        event: 'Corridor Over-Speeding Clocked',
        detail: 'Vehicle clocked @ 68.4 km/h in 40 km/h Market Road zone (+28.4 km/h)',
        camId: 'CAM-06',
        confidence: 96.8,
        plate: 'JW-4451',
        speed: 68.4,
        vehicle: 'Honda Civic (Silver)',
      },
      // Critical (High Severity -> Popup alert + Siren beeping on Live Wall)
      {
        modelId: 'fire',
        severity: 'high' as const,
        event: 'Smoke Plume & Flame Signature',
        detail: 'Thermal luminescence and dense smoke plume detected on rooftop structure',
        camId: 'CAM-02',
        confidence: 97.8,
      },
      // Non-critical (Medium Severity -> Bottom Right Toast Notification)
      {
        modelId: 'parking',
        severity: 'medium' as const,
        event: 'Illegal Emergency Red-Curb Parking',
        detail: 'White Toyota parked in restricted emergency corridor lane >12 mins',
        camId: 'CAM-02',
        confidence: 94.3,
        plate: 'FD-1092',
        vehicle: 'Toyota Yaris',
      },
      // Critical (High Severity -> Popup alert + Siren beeping on Live Wall)
      {
        modelId: 'wrongway',
        severity: 'high' as const,
        event: 'Wrong-Way Vehicle in Arterial',
        detail: 'Vehicle heading opposite to designated one-way flow at Corridor Exit',
        camId: 'CAM-08',
        confidence: 96.1,
        speed: 38.5,
        plate: 'ICT-4421',
      },
      // Non-critical (Medium Severity -> Bottom Right Toast Notification)
      {
        modelId: 'mob',
        severity: 'medium' as const,
        event: 'Mob / Crowd Density Alert',
        detail: 'Cluster of 11 persons formed outside school entrance gate',
        camId: 'CAM-07',
        confidence: 93.1,
      },
      // Critical (High Severity -> Popup alert + Siren beeping on Live Wall)
      {
        modelId: 'wallbreach',
        severity: 'high' as const,
        event: 'Perimeter Wall Intrusion',
        detail: 'Boundary scaling detected along Sector C North-East perimeter fence',
        camId: 'CAM-04',
        confidence: 95.2,
      },
      // Non-critical (Low Severity -> Bottom Right Toast Notification)
      {
        modelId: 'anpr',
        severity: 'low' as const,
        event: 'Vehicle ANPR Profile Scanned',
        detail: 'Silver Honda Civic [CUS-4005] verified entering Gate 1 inbound lane',
        camId: 'CAM-01',
        confidence: 98.6,
        plate: 'CUS-4005',
        vehicle: 'Honda Civic',
      },
      // Critical (High Severity -> Popup alert + Siren beeping on Live Wall)
      {
        modelId: 'falling',
        severity: 'high' as const,
        event: 'Pedestrian Fall / Medical Alert',
        detail: 'Rapid vertical descent detected; individual in horizontal posture >15s',
        camId: 'CAM-03',
        confidence: 94.6,
      },
    ]

    let activeTimer: number | null = null

    const scheduleNext = () => {
      const delay = Math.floor(Math.random() * 8000) + 8000
      activeTimer = window.setTimeout(() => {
        const scenario = LIVE_SCENARIOS[scenarioIndexRef.current % LIVE_SCENARIOS.length]
        scenarioIndexRef.current += 1

        const currentCams = camerasRef.current
        const cam = currentCams.find((c) => c.id === scenario.camId) || currentCams[0]
        if (!cam) {
          scheduleNext()
          return
        }

        const sev = severityRef.current(scenario.modelId) || scenario.severity
        const at = Date.now()
        const clockLabel = new Date(at).toLocaleString('en-GB', { hour12: false })

        const inc: Incident = {
          id: `${cam.id}-${scenario.modelId}-${at}`,
          firedAt: at,
          clockLabel,
          cameraId: cam.id,
          cameraIndex: cam.index,
          cameraName: cam.name,
          zone: cam.zone,
          ip: cam.ip,
          modelId: scenario.modelId,
          event: scenario.event,
          detail: scenario.detail,
          severity: sev,
          confidence: scenario.confidence,
          plate: scenario.plate,
          vehicle: scenario.vehicle,
          speed: scenario.speed,
          acknowledged: false,
          dispatched: false,
        }

        pushIncident(inc)

        if (sev === 'high') {
          setCriticalAlert((cur) => cur ?? inc)
          focusCamera(cam.id)
        } else {
          blip()
          const toast: Toast = {
            id: `t-${inc.id}`,
            incidentId: inc.id,
            title: inc.event,
            detail: inc.detail,
            cameraLabel: `CAM ${cam.index} · ${cam.zone}`,
            severity: sev,
          }
          setToasts((prev) => [...prev.slice(-3), toast])
          window.setTimeout(() => {
            setToasts((tp) => tp.filter((t) => t.id !== toast.id))
          }, 12000)
        }

        scheduleNext()
      }, delay)
    }

    scheduleNext()

    return () => {
      if (activeTimer) window.clearTimeout(activeTimer)
    }
  }, [tab, playing, focusCamera, pushIncident])

  // siren tied to critical alert on Live Wall tab
  const soundRef = useRef(soundEnabled)
  useEffect(() => {
    soundRef.current = soundEnabled
    if (!soundEnabled) stopSiren()
  }, [soundEnabled])
  useEffect(() => {
    if (criticalAlert && soundRef.current && tab === 'wall') playSiren()
    else stopSiren()
  }, [criticalAlert, tab])

  const value = useMemo<AppState>(
    () => ({
      now,
      theme,
      setTheme,
      toggleTheme,
      hardware,
      role,
      setRole,
      canEdit,
      tab,
      setTab,
      sidebarCollapsed,
      setSidebarCollapsed,
      toggleSidebar,
      cameras,
      getCamera,
      setCameraVideo,
      moveCamera,
      updateCameraDetails,
      setCameraModels,
      toggleCameraModel,
      addCamera,
      deleteCamera,
      mountCustomVideo,
      models,
      severityOverrides,
      setSeverity,
      severityOf,
      layout,
      setLayout,
      order,
      focusCamera,
      swapTiles,
      mainId,
      playing,
      setPlaying,
      speed,
      setSpeed,
      forensicCameraId,
      openForensic,
      closeForensic,
      incidents,
      toasts,
      dismissToast,
      criticalAlert,
      acknowledgeAlert,
      soundEnabled,
      setSoundEnabled,
      resetSimulation,
      activityFeed,
      dismissFeedEntry,
      acknowledgeIncident,
      reportPeriod,
      setReportPeriod,
      customRange,
      setCustomRange,
    }),
    [
      now, theme, setTheme, toggleTheme, hardware, role, canEdit, tab, sidebarCollapsed, toggleSidebar, cameras, getCamera, setCameraVideo, moveCamera,
      updateCameraDetails, setCameraModels, toggleCameraModel, addCamera,
      deleteCamera, mountCustomVideo, models, severityOverrides, setSeverity, severityOf, layout,
      order, focusCamera, swapTiles, mainId, playing, speed, forensicCameraId,
      openForensic, closeForensic, incidents, toasts, dismissToast,
      criticalAlert, acknowledgeAlert, soundEnabled, resetSimulation,
      activityFeed, dismissFeedEntry, acknowledgeIncident, reportPeriod,
      customRange,
    ],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
