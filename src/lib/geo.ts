import { SURVEY_TRACK, SURVEY_WAYPOINTS, type SurveyWaypoint } from '../data/navalAnchorageSurvey'
import { STORAGE_KEYS } from '../constants'
import type { Camera, Incident, Severity } from '../types'
import { loadJSON, saveJSON } from './storage'

/**
 * Geographic helpers for the Tactical Map.
 *
 * Projection: local equirectangular (east/north metres from a fixed origin,
 * longitude scaled by cos(latitude of origin)). The whole survey spans
 * ~4 x 4 km, where this differs from true geodesic distance by well under
 * 0.1 % — far below GPS fix error (~3-5 m). Markers, track and heatmap all
 * go through the same `project()` so they can never drift apart.
 */

const ORIGIN_LAT = 33.58
const ORIGIN_LON = 73.19
const M_PER_DEG_LAT = 110_540
const M_PER_DEG_LON = 111_320 * Math.cos((ORIGIN_LAT * Math.PI) / 180)

/** Rough envelope of Naval Anchorage + approach roads; anything outside is treated as a bad fix. */
const VALID_BOUNDS = { minLat: 33.5, maxLat: 33.65, minLon: 73.1, maxLon: 73.28 }

export interface XY {
  x: number
  y: number
}

/** WGS84 lat/lon → map metres (x east, y south so it matches SVG screen axes). */
export function project(lat: number, lon: number): XY {
  return {
    x: (lon - ORIGIN_LON) * M_PER_DEG_LON,
    y: -(lat - ORIGIN_LAT) * M_PER_DEG_LAT,
  }
}

export function isValidLatLon(lat: unknown, lon: unknown): lat is number {
  return (
    typeof lat === 'number' &&
    typeof lon === 'number' &&
    Number.isFinite(lat) &&
    Number.isFinite(lon) &&
    lat >= VALID_BOUNDS.minLat &&
    lat <= VALID_BOUNDS.maxLat &&
    lon >= VALID_BOUNDS.minLon &&
    lon <= VALID_BOUNDS.maxLon
  )
}

/** Surveyed camera sites, keyed `WP-<n>`. Invalid fixes are reported, never placed. */
export interface CameraSite extends SurveyWaypoint {
  siteId: string
  pos: XY
}

export const CAMERA_SITES: CameraSite[] = []
export const INVALID_SITES: SurveyWaypoint[] = []
for (const w of SURVEY_WAYPOINTS) {
  if (isValidLatLon(w.lat, w.lon)) {
    CAMERA_SITES.push({ ...w, siteId: `WP-${w.n}`, pos: project(w.lat, w.lon) })
  } else {
    INVALID_SITES.push(w)
  }
}
if (INVALID_SITES.length > 0) {
  console.warn('[geo] survey waypoints with invalid coordinates (not placed):', INVALID_SITES)
}

export const SITE_BY_ID = new Map(CAMERA_SITES.map((s) => [s.siteId, s]))

export const TRACK_XY: XY[][] = SURVEY_TRACK.map((seg) =>
  seg.filter(([lat, lon]) => isValidLatLon(lat, lon)).map(([lat, lon]) => project(lat, lon)),
)

/** Map extent in metres, padded, covering the track and every valid site. */
export const MAP_EXTENT = (() => {
  const all = [...TRACK_XY.flat(), ...CAMERA_SITES.map((s) => s.pos)]
  const xs = all.map((p) => p.x)
  const ys = all.map((p) => p.y)
  const pad = 150
  const minX = Math.min(...xs) - pad
  const minY = Math.min(...ys) - pad
  return { minX, minY, width: Math.max(...xs) + pad - minX, height: Math.max(...ys) + pad - minY }
})()

/* ── Camera → surveyed site assignment ─────────────────────────────────────
 * The demo feeds (CAM-01..08) were not part of the field survey, so which
 * surveyed site each feed represents is a deployment decision. These
 * defaults pair each feed with the site whose recorded name/purpose matches
 * the feed's detection models; operators can reassign in Edit Mode. Cameras
 * with no assignment are listed as "not placed" — never given a dummy spot.
 */
export const DEFAULT_CAMERA_SITES: Record<string, string> = {
  'CAM-01': 'WP-2', // Main Boulevard Gate 1 (ANPR/speed) → "Main gate"
  'CAM-02': 'WP-50', // Jamia Mosque Rd → "Muhammad masjid 2 camera"
  'CAM-03': 'WP-32', // Community Park → "C park 2 camera"
  'CAM-04': 'WP-23', // Sector C Junction (accident) → "A Chowk 3 camera"
  'CAM-05': 'WP-37', // Checkpoint gate (helmet/ANPR) → "Japan gate"
  'CAM-06': 'WP-51', // Speed estimation feed → "Speed Radar 1 camera"
  'CAM-07': 'WP-28', // School Gate (mob) → "Briane school 2 camera"
  'CAM-08': 'WP-34', // Commercial corridor exit (wrong-way) → "commercial 2 exit 2 camera"
}

/** `null` = explicitly unassigned by an operator. */
export type CameraSiteOverrides = Record<string, string | null>

export function loadCameraSiteOverrides(): CameraSiteOverrides {
  const v = loadJSON<CameraSiteOverrides>(STORAGE_KEYS.cameraSites, {})
  return v && typeof v === 'object' ? v : {}
}

export function saveCameraSiteOverrides(overrides: CameraSiteOverrides): void {
  saveJSON(STORAGE_KEYS.cameraSites, overrides)
}

export function siteIdFor(camId: string, overrides: CameraSiteOverrides): string | null {
  const id = camId in overrides ? overrides[camId] : DEFAULT_CAMERA_SITES[camId]
  return id && SITE_BY_ID.has(id) ? id : null
}

export function siteFor(cam: Camera, overrides: CameraSiteOverrides): CameraSite | null {
  const id = siteIdFor(cam.id, overrides)
  return id ? SITE_BY_ID.get(id) ?? null : null
}

/* ── Incident heat ─────────────────────────────────────────────────────────
 * Incidents carry no GPS of their own (only cameraId), so every incident is
 * located at its camera's surveyed site: a camera-based approximation, NOT
 * the exact incident position. Weight per incident = severity weight below.
 */
export const SEVERITY_WEIGHT: Record<Severity, number> = { high: 3, medium: 2, low: 1 }

export interface HeatPoint {
  pos: XY
  weight: number
  count: number
  siteId: string
  /** always 'camera' today; 'exact' reserved for incidents that carry their own GPS */
  basis: 'camera' | 'exact'
}

export interface HeatResult {
  points: HeatPoint[]
  mapped: number
  /** incidents whose camera has no surveyed site (deleted/unassigned) */
  unmapped: number
}

export function incidentHeat(
  incidents: Incident[],
  cameras: Camera[],
  overrides: CameraSiteOverrides,
): HeatResult {
  const bySite = new Map<string, HeatPoint>()
  let unmapped = 0
  const camById = new Map(cameras.map((c) => [c.id, c]))
  for (const inc of incidents) {
    const cam = camById.get(inc.cameraId)
    const site = cam ? siteFor(cam, overrides) : null
    if (!site) {
      unmapped++
      continue
    }
    const p = bySite.get(site.siteId) ?? { pos: site.pos, weight: 0, count: 0, siteId: site.siteId, basis: 'camera' as const }
    p.weight += SEVERITY_WEIGHT[inc.severity] ?? 1
    p.count++
    bySite.set(site.siteId, p)
  }
  return { points: [...bySite.values()], mapped: incidents.length - unmapped, unmapped }
}

/** Heat ramp: cyan (low) → yellow (moderate) → orange (high) → red (critical). */
const RAMP: [number, [number, number, number]][] = [
  [0.0, [22, 184, 212]],
  [0.35, [234, 179, 8]],
  [0.65, [249, 115, 22]],
  [1.0, [239, 68, 68]],
]

function rampColor(t: number): [number, number, number] {
  for (let i = 1; i < RAMP.length; i++) {
    const [t1, c1] = RAMP[i]
    const [t0, c0] = RAMP[i - 1]
    if (t <= t1) {
      const f = (t - t0) / (t1 - t0)
      return [0, 1, 2].map((k) => Math.round(c0[k] + (c1[k] - c0[k]) * f)) as [number, number, number]
    }
  }
  return RAMP[RAMP.length - 1][1]
}

/**
 * Gaussian kernel density over the map extent, rendered to a PNG data URL
 * that is drawn as an SVG <image> in the same metre coordinates as markers.
 * Intensity at a cell = Σ weight · exp(-d²/2σ²); colours are normalised to the
 * peak of the current data, so the ramp shows RELATIVE concentration.
 */
export const HEAT_SIGMA_M = 110

export function renderHeatImage(points: HeatPoint[], cellM = 10): string | null {
  if (points.length === 0 || typeof document === 'undefined') return null
  const { minX, minY, width, height } = MAP_EXTENT
  const w = Math.ceil(width / cellM)
  const h = Math.ceil(height / cellM)
  const grid = new Float32Array(w * h)
  const reach = Math.ceil((HEAT_SIGMA_M * 3) / cellM)
  const twoSig2 = 2 * HEAT_SIGMA_M * HEAT_SIGMA_M
  for (const p of points) {
    // pixel (x, y) covers [minX + x·cell, minX + (x+1)·cell); sample at its centre
    const px = p.pos.x - minX
    const py = p.pos.y - minY
    const cx = Math.floor(px / cellM)
    const cy = Math.floor(py / cellM)
    for (let y = Math.max(0, cy - reach); y <= Math.min(h - 1, cy + reach); y++) {
      for (let x = Math.max(0, cx - reach); x <= Math.min(w - 1, cx + reach); x++) {
        const dx = (x + 0.5) * cellM - px
        const dy = (y + 0.5) * cellM - py
        grid[y * w + x] += p.weight * Math.exp(-(dx * dx + dy * dy) / twoSig2)
      }
    }
  }
  let max = 0
  for (let i = 0; i < grid.length; i++) if (grid[i] > max) max = grid[i]
  if (max <= 0) return null
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  const img = ctx.createImageData(w, h)
  for (let i = 0; i < grid.length; i++) {
    const t = grid[i] / max
    if (t < 0.04) continue
    const [r, g, b] = rampColor(t)
    img.data[i * 4] = r
    img.data[i * 4 + 1] = g
    img.data[i * 4 + 2] = b
    // fade in from the edge of the kernel; ~85 % opaque at the peak
    img.data[i * 4 + 3] = Math.round(255 * Math.min(1, t * 3) * (0.35 + 0.5 * t))
  }
  ctx.putImageData(img, 0, 0)
  return canvas.toDataURL('image/png')
}
