import {
  LayoutDashboard,
  Monitor,
  MapPin,
  Search,
  Route,
  AlertCircle,
  Camera as CameraIcon,
  Gauge,
  ScanLine,
  Shield,
} from 'lucide-react'
import { useApp } from '../store/AppContext'
import type { TabId } from '../types'

interface NavItem {
  id: TabId
  label: string
  icon: any
  desc: string
}

const TABS: NavItem[] = [
  { id: 'wall', label: 'Live Wall Surveillance', icon: Monitor, desc: 'Multi-Camera Stream Grid' },
  { id: 'map', label: 'GIS Tactical Map', icon: MapPin, desc: 'Society Nodes & Coordinates' },
  { id: 'models', label: 'Number Plate Scanner', icon: ScanLine, desc: 'ANPR & Fast OCR' },
  { id: 'overview', label: 'Main Safety Overview', icon: LayoutDashboard, desc: 'Command Center & KPIs' },
  { id: 'models', label: 'Vehicle Speed Radar', icon: Gauge, desc: 'Live Radar & Speed Limit Slider' },

  { id: 'forensics', label: 'Forensics & Evidence', icon: Search, desc: 'Video Playback Inspection' },
  { id: 'trajectory', label: 'Re-ID Trajectory Search', icon: Route, desc: 'Multi-Camera Tracking' },
  { id: 'incidents', label: 'Incident Log & Alerts', icon: AlertCircle, desc: 'E-Challans & SOS Reports' },
  { id: 'cameras', label: 'Camera Node Feeds', icon: CameraIcon, desc: 'RTSP Feeds & Settings' },
]

export default function Sidebar() {
  const { tab, setTab, incidents, sidebarCollapsed } = useApp()
  const criticalCount = incidents.filter((i) => i.severity === 'high' && !i.acknowledged).length

  return (
    <aside
      className={`flex flex-col select-none shrink-0 transition-all duration-300 ease-in-out border-r border-edge ${sidebarCollapsed ? 'w-20 px-2 py-4' : 'w-64 px-3 py-4'
        }`}
    >
      {/* Title / Mini Header */}
      {sidebarCollapsed ? (
        <div
          className="flex items-center justify-center pb-3 text-slate-400"
          title="Safety Monitoring Cameras"
        >
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-500">
            <Shield className="h-3.5 w-3.5" />
          </div>
        </div>
      ) : (
        <div className="text-[11px] font-bold tracking-wider uppercase text-slate-500 px-3 pb-3 truncate">
          SAFETY MONITORING CAMERAS
        </div>
      )}

      {/* Nav List */}
      <nav className="space-y-2 flex-1 overflow-y-auto pr-0.5">
        {TABS.map(({ id, label, icon: Icon, desc }, idx) => {
          const isUniqueTab = idx === 0 || idx === 1 || idx >= 3
          if (!isUniqueTab) return null

          const active = tab === id && (idx === 1 ? true : tab === id)
          const hasCritical = id === 'incidents' && criticalCount > 0

          return (
            <button
              key={`${id}-${idx}`}
              onClick={() => setTab(id)}
              className={`w-full relative flex items-center transition-all ${sidebarCollapsed
                ? 'justify-center p-3 rounded-2xl'
                : 'justify-between gap-3 px-3.5 py-3 rounded-2xl text-left'
                } ${active
                  ? 'neo-inset-sm font-bold text-blue-600 dark:text-cyan-400 border border-blue-400/40 dark:border-cyan-500/40'
                  : 'neo-btn text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-white'
                }`}
              title={sidebarCollapsed ? `${label} (${desc})` : desc}
            >
              <div
                className={`flex items-center min-w-0 ${sidebarCollapsed ? 'justify-center' : 'gap-3'
                  }`}
              >
                <Icon
                  className={`flex-shrink-0 transition-transform ${sidebarCollapsed ? 'h-5 w-5' : 'h-4.5 w-4.5'
                    } ${active ? 'text-blue-600 dark:text-cyan-400 scale-105' : 'text-slate-400'
                    }`}
                />
                {!sidebarCollapsed && (
                  <div className="truncate min-w-0">
                    <div className="text-xs font-semibold leading-tight truncate font-sans">
                      {label}
                    </div>
                    <div className="text-[10px] text-slate-500 truncate leading-none mt-0.5">
                      {desc}
                    </div>
                  </div>
                )}
              </div>

              {/* Badges */}
              {hasCritical && (
                <span
                  className={`inline-flex items-center justify-center rounded-full bg-rose-500 font-bold text-white shadow-sm animate-pulse ${sidebarCollapsed
                    ? 'absolute -top-1 -right-1 h-5 w-5 text-[9px]'
                    : 'px-2 py-0.5 text-[10px]'
                    }`}
                >
                  {criticalCount}
                </span>
              )}
            </button>
          )
        })}
      </nav>

      {/* Footer: Officer Status matching Screenshot */}
      <div className="pt-3 border-t border-edge">
        {sidebarCollapsed ? (
          <div
            className="neo-card-sm p-2 flex flex-col items-center justify-center relative cursor-default"
            title="Duty Officer: Traffic Enforcement (Authorized)"
          >
            <div className="relative flex h-8 w-8 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400 font-bold text-xs font-mono">
              OP
              <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-emerald-500 border border-base"></span>
            </div>
          </div>
        ) : (
          <div className="neo-card-sm p-3 flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400 font-bold text-xs font-mono">
              OP
            </div>
            <div className="min-w-0 text-xs">
              <div className="font-bold text-slate-800 dark:text-slate-200 truncate">
                Traffic Enforcement
              </div>
              <div className="text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold flex items-center gap-1">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 inline-block"></span>
                Status: Authorized
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  )
}
