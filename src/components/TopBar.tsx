import { useState, useRef, useEffect } from 'react'
import {
  Volume2,
  VolumeX,
  RefreshCw,
  Sun,
  Moon,
  Shield,
  Menu,
  ChevronRight,
  Bell,
  Check,
  ExternalLink,
  MessageCircle,
  AlertTriangle,
  Flame,
  Clock,
} from 'lucide-react'
import { useApp } from '../store/AppContext'
import { SITE_TAGLINE, ROLE_LABELS, DUTY_OFFICER } from '../constants'
import { fmtClock } from '../lib/format'
import { blip } from '../lib/audio'
import type { Incident } from '../types'

export default function TopBar() {
  const {
    role,
    setRole,
    soundEnabled,
    setSoundEnabled,
    resetSimulation,
    theme,
    toggleTheme,
    tab,
    setTab,
    sidebarCollapsed,
    toggleSidebar,
    cameras,
    incidents,
    acknowledgeIncident,
  } = useApp()

  const [showNotifications, setShowNotifications] = useState(false)
  const notifRef = useRef<HTMLDivElement>(null)

  // Close notifications dropdown on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (notifRef.current && !notifRef.current.contains(event.target as Node)) {
        setShowNotifications(false)
      }
    }
    if (showNotifications) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [showNotifications])

  const doReset = () => {
    if (
      window.confirm(
        'Reset Simulation? This clears the fired-events set and incident log so the full sequence can replay.',
      )
    ) {
      resetSimulation()
    }
  }

  // Format date like: "Wed, Aug 19"
  const dateFormatted = new Date().toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })

  // Tab Breadcrumb Label
  const tabNames: Record<string, string> = {
    overview: 'Main Safety Overview',
    models: 'Vehicle Speed Radar & AI Models',
    wall: 'Live Multi-Camera Wall',
    map: 'GIS Tactical Map',
    forensics: 'Forensics & Video Playback',
    trajectory: 'Re-ID Trajectory Search',
    incidents: 'Incident Log & E-Challans',
    cameras: 'Camera Node Feeds',
  }

  // Active cameras calculation (e.g. 8/8 active)
  const totalCams = cameras.length || 8
  const activeCams = cameras.length || 8 // All currently streaming nodes
  const activeRatio = totalCams > 0 ? activeCams / totalCams : 1

  // Dynamic Red-to-Green scale color
  const statusScaleStyle =
    activeRatio >= 0.9
      ? {
          container:
            'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/30',
          dot: 'bg-emerald-500',
        }
      : activeRatio >= 0.6
      ? {
          container:
            'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/30',
          dot: 'bg-amber-500',
        }
      : {
          container:
            'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/30',
          dot: 'bg-rose-500',
        }

  // Unacknowledged alerts count
  const unacknowledged = incidents.filter((i) => !i.acknowledged)
  const unackCount = unacknowledged.length
  const recentIncidents = incidents.slice(0, 6)

  const handleAcknowledgeAll = () => {
    unacknowledged.forEach((i) => acknowledgeIncident(i.id))
  }

  const getWaLink = (inc: Incident) => {
    const label = inc.severity === 'high' ? '🚨 CRITICAL' : inc.severity === 'medium' ? '⚠️ WARNING' : 'ℹ️ ADVISORY'
    const msg = `${label} — Naval Anchorage SafeCity\n${inc.event}\nCAM ${inc.cameraIndex} · ${inc.zone}\nTime: ${inc.clockLabel}`
    return `https://wa.me/${DUTY_OFFICER.whatsapp}?text=${encodeURIComponent(msg)}`
  }

  return (
    <header className="flex items-center justify-between px-4 sm:px-6 py-2.5 z-30 transition-all select-none border-b border-edge">
      {/* Left: Branding & Breadcrumbs */}
      <div className="flex items-center gap-3.5">
        {/* Neomorphic Hamburger button */}
        <button
          onClick={toggleSidebar}
          className={`neo-btn p-2 rounded-xl transition-all ${
            sidebarCollapsed
              ? 'text-blue-600 dark:text-cyan-400 neo-inset-sm'
              : 'text-slate-400 hover:text-blue-500'
          }`}
          title={sidebarCollapsed ? 'Expand Navigation Sidebar' : 'Collapse Navigation Sidebar'}
        >
          <Menu className="h-4.5 w-4.5" />
        </button>

        {/* Shield Crest */}
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-600/15 border border-blue-500/30 text-blue-500 shadow-sm">
            <Shield className="h-5 w-5 fill-blue-500/20 stroke-blue-600 dark:stroke-blue-400" />
          </div>
          <div>
            <div className="text-base font-extrabold tracking-tight leading-none text-slate-900 dark:text-white font-sans">
              Sahil-e-Baseera
            </div>
            <div className="text-[10px] font-semibold tracking-wider text-slate-500 leading-none mt-1 uppercase">
              {SITE_TAGLINE}
            </div>
          </div>
        </div>

        {/* Breadcrumb path */}
        <div className="hidden md:flex items-center gap-1.5 ml-4 pl-4 border-l border-edge text-xs">
          <span className="text-slate-400 font-medium">Home</span>
          <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
          <span className="font-bold text-blue-600 dark:text-blue-400">
            {tabNames[tab] || 'Command Center'}
          </span>
        </div>
      </div>

      {/* Right: Status, Controls, Notifications, Clock */}
      <div className="flex items-center gap-2.5 sm:gap-3">
        {/* Dynamic Cameras Active Badge with Red-to-Green Scale */}
        <div
          className={`hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-bold border transition-all ${statusScaleStyle.container}`}
          title={`${activeCams} out of ${totalCams} cameras active & transmitting telemetry`}
        >
          <span className={`h-2 w-2 rounded-full ${statusScaleStyle.dot} animate-pulse`}></span>
          <span>
            {activeCams}/{totalCams} Active Cameras
          </span>
        </div>

        {/* Notifications Button & Dropdown */}
        <div className="relative" ref={notifRef}>
          <button
            onClick={() => setShowNotifications((prev) => !prev)}
            className={`neo-btn p-2 relative transition-all ${
              showNotifications ? 'neo-inset-sm text-blue-600 dark:text-cyan' : 'text-slate-500 hover:text-blue-600'
            }`}
            title="System Alert Notifications"
          >
            <Bell className="h-4 w-4" />
            {unackCount > 0 && (
              <span className="absolute -top-1 -right-1 flex h-4 min-w-[16px] px-1 items-center justify-center rounded-full bg-rose-500 text-[9px] font-bold text-white shadow-sm animate-pulse">
                {unackCount}
              </span>
            )}
          </button>

          {/* Notifications Dropdown Modal */}
          {showNotifications && (
            <div className="absolute right-0 mt-2 w-80 sm:w-96 rounded-2xl border border-slate-200 dark:border-[#293B52] bg-slate-50 dark:bg-[#17263A] shadow-2xl z-50 overflow-hidden animate-confirm-pop">
              {/* Dropdown Header */}
              <div className="flex items-center justify-between border-b border-slate-200 dark:border-[#293B52] px-4 py-3 bg-white dark:bg-[#111D2E]">
                <div className="flex items-center gap-2">
                  <Bell className="h-4 w-4 text-blue-600 dark:text-cyan" />
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-800 dark:text-slate-100">
                    Notifications
                  </span>
                  {unackCount > 0 && (
                    <span className="rounded-full bg-rose-500/15 text-rose-700 dark:text-rose-400 px-2 py-0.2 text-[10px] font-bold border border-rose-500/30">
                      {unackCount} new
                    </span>
                  )}
                </div>
                {unackCount > 0 && (
                  <button
                    onClick={handleAcknowledgeAll}
                    className="text-[10px] font-semibold text-blue-600 dark:text-cyan hover:underline"
                  >
                    Acknowledge all
                  </button>
                )}
              </div>

              {/* Incidents List */}
              <div className="max-h-80 overflow-y-auto divide-y divide-slate-200 dark:divide-slate-800">
                {recentIncidents.length === 0 ? (
                  <div className="py-8 text-center text-xs text-slate-400">
                    No recent alert notifications
                  </div>
                ) : (
                  recentIncidents.map((inc) => {
                    const isCrit = inc.severity === 'high'
                    const isWarn = inc.severity === 'medium'
                    return (
                      <div
                        key={inc.id}
                        className={`p-3 transition-colors ${
                          !inc.acknowledged
                            ? isCrit
                              ? 'bg-rose-500/10 dark:bg-rose-950/40'
                              : 'bg-amber-500/10 dark:bg-amber-950/40'
                            : 'hover:bg-slate-100 dark:hover:bg-slate-900/60'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-1.5">
                            {isCrit ? (
                              <Flame className="h-3.5 w-3.5 text-rose-500 shrink-0" />
                            ) : isWarn ? (
                              <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0" />
                            ) : (
                              <Clock className="h-3.5 w-3.5 text-blue-500 shrink-0" />
                            )}
                            <span
                              className={`text-xs font-bold leading-tight ${
                                isCrit
                                  ? 'text-rose-700 dark:text-rose-400'
                                  : isWarn
                                  ? 'text-amber-700 dark:text-amber-400'
                                  : 'text-blue-700 dark:text-cyan'
                              }`}
                            >
                              {inc.event}
                            </span>
                          </div>
                          <span className="text-[10px] text-slate-400 font-mono whitespace-nowrap">
                            CAM {inc.cameraIndex}
                          </span>
                        </div>

                        <p className="text-[11px] text-slate-600 dark:text-slate-300 mt-1 line-clamp-2 leading-relaxed font-medium">
                          {inc.detail}
                        </p>

                        <div className="flex items-center justify-between mt-2 pt-1 border-t border-slate-200 dark:border-[#293B52]">
                          <span className="text-[9px] font-mono text-slate-400">
                            {inc.clockLabel.split(', ')[1] || inc.clockLabel}
                          </span>

                          <div className="flex items-center gap-1.5">
                            <a
                              href={getWaLink(inc)}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={() => blip()}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-semibold bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-500/25 border border-emerald-600/30"
                              title="Notify via WhatsApp"
                            >
                              <MessageCircle className="h-2.5 w-2.5" />
                              WA
                              <ExternalLink className="h-2 w-2 opacity-60" />
                            </a>

                            {!inc.acknowledged && (
                              <button
                                onClick={() => acknowledgeIncident(inc.id)}
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-semibold bg-blue-600/10 dark:bg-cyan/10 text-blue-700 dark:text-cyan hover:bg-blue-600/20 dark:hover:bg-cyan/20 border border-blue-600/30 dark:border-cyan/30"
                                title="Acknowledge"
                              >
                                <Check className="h-2.5 w-2.5" />
                                Ack
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>

              {/* Dropdown Footer */}
              <div className="border-t border-slate-200 dark:border-[#293B52] p-2 bg-white dark:bg-[#111D2E] text-center">
                <button
                  onClick={() => {
                    setTab('incidents')
                    setShowNotifications(false)
                  }}
                  className="text-xs font-bold text-blue-600 dark:text-cyan hover:underline py-1 w-full"
                >
                  View All in Incident Log →
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Role Selector */}
        <select
          value={role}
          onChange={(e) => setRole(e.target.value as any)}
          className="neo-inset-sm text-xs px-2.5 py-1.5 rounded-xl border border-edge bg-surface2 font-medium text-slate-700 dark:text-slate-300 focus:outline-none"
        >
          {Object.entries(ROLE_LABELS).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>

        {/* Reset */}
        <button
          onClick={doReset}
          className="neo-btn p-2 text-slate-400 hover:text-amber-500"
          title="Reset Simulation"
        >
          <RefreshCw className="h-4 w-4" />
        </button>

        {/* Audio Toggle */}
        <button
          onClick={() => setSoundEnabled(!soundEnabled)}
          className="neo-btn p-2 text-slate-400 hover:text-cyan"
          title={soundEnabled ? 'Mute Alert Audio' : 'Unmute Audio'}
        >
          {soundEnabled ? (
            <Volume2 className="h-4 w-4 text-cyan" />
          ) : (
            <VolumeX className="h-4 w-4" />
          )}
        </button>

        {/* Theme Toggle Button (Light/Dark Neomorphism) */}
        <button
          onClick={toggleTheme}
          className="neo-btn p-2 text-slate-700 dark:text-slate-200 hover:text-blue-600"
          title={theme === 'dark' ? 'Switch to Light Neomorphism' : 'Switch to Dark Neomorphism'}
        >
          {theme === 'dark' ? (
            <Sun className="h-4 w-4 text-amber-400" />
          ) : (
            <Moon className="h-4 w-4 text-blue-600" />
          )}
        </button>

        {/* Digital Clock & Date */}
        <div className="text-right leading-none pl-2 border-l border-edge">
          <div className="font-mono text-sm font-bold tracking-tight text-slate-900 dark:text-slate-100">
            {fmtClock(new Date())}
          </div>
          <div className="text-[10px] text-slate-500 font-medium mt-0.5">
            {dateFormatted}
          </div>
        </div>
      </div>
    </header>
  )
}
