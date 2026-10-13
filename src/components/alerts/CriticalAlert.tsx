import { X, MessageCircle, ExternalLink, Focus } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import { DUTY_OFFICER, SEVERITY_META } from '../../constants'
import { blip } from '../../lib/audio'
import ModelBadge from '../ui/ModelBadge'

export default function CriticalAlert() {
  const { criticalAlert, acknowledgeAlert, canEdit, focusCamera } = useApp()

  if (!criticalAlert) return null

  const sev = SEVERITY_META.high

  /**
   * FOCUS STREAM: moves the offending camera into the primary tile (via the
   * existing order-swap — videos stay keyed by camera id, so no reload) and
   * closes the modal.
   */
  const focusStream = () => {
    focusCamera(criticalAlert.cameraId)
    acknowledgeAlert()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md animate-confirm-pop rounded-2xl border-2 border-rose-500 bg-slate-50 dark:bg-[#17263A] shadow-2xl overflow-hidden">
        {/* Header */}
        <div
          className="flex items-center justify-between border-b-2 border-rose-500/40 px-6 py-4 bg-rose-500/10 dark:bg-rose-950/40"
        >
          <div className="flex items-center gap-3">
            <div className="h-3 w-3 rounded-full bg-rose-500 animate-pulse shadow-sm" />
            <span className="text-base font-extrabold tracking-wider uppercase text-rose-600 dark:text-rose-400 font-sans">
              {sev.label} ALERT
            </span>
          </div>
          {!canEdit && (
            <button
              onClick={acknowledgeAlert}
              className="p-1 rounded-lg text-slate-500 hover:text-slate-800 dark:hover:text-white transition"
              title="Acknowledge"
            >
              <X className="h-5 w-5" />
            </button>
          )}
        </div>

        {/* Content */}
        <div className="space-y-4 px-6 py-5">
          {/* Event title + detail */}
          <div>
            <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100 mb-1.5 leading-snug">
              {criticalAlert.event}
            </h2>
            <p className="text-sm font-medium text-slate-600 dark:text-slate-300 leading-relaxed">
              {criticalAlert.detail}
            </p>
          </div>

          {/* Camera + zone */}
          <div className="rounded-xl border border-slate-200 dark:border-[#293B52] bg-white dark:bg-[#111D2E] p-4 space-y-2.5 text-sm shadow-inner">
            <div className="flex justify-between items-start gap-4">
              <span className="text-slate-500 dark:text-slate-400 shrink-0 select-none font-medium">Camera:</span>
              <span className="font-mono font-bold text-amber-700 dark:text-amber-400 text-right break-words min-w-0">
                CAM {criticalAlert.cameraIndex} — {criticalAlert.cameraName}
              </span>
            </div>
            <div className="flex justify-between items-start gap-4">
              <span className="text-slate-500 dark:text-slate-400 shrink-0 select-none font-medium">Zone:</span>
              <span className="font-bold text-slate-800 dark:text-slate-200 text-right break-words min-w-0">{criticalAlert.zone}</span>
            </div>
            <div className="flex justify-between items-center gap-4">
              <span className="text-slate-500 dark:text-slate-400 shrink-0 select-none font-medium">Time:</span>
              <span className="font-mono font-semibold text-blue-700 dark:text-cyan text-right shrink-0">{criticalAlert.clockLabel}</span>
            </div>
            <div className="flex justify-between items-center gap-4">
              <span className="text-slate-500 dark:text-slate-400 shrink-0 select-none font-medium">Confidence:</span>
              <span className="font-bold text-amber-700 dark:text-amber-400 text-right shrink-0">{criticalAlert.confidence}%</span>
            </div>
          </div>

          {/* Model badge */}
          <div className="flex items-center">
            <ModelBadge id={criticalAlert.modelId} />
          </div>

          {/* WhatsApp quick-notify (real deep-link) */}
          {canEdit && (
            <div className="border-t border-slate-200 dark:border-[#293B52] pt-3">
              <a
                href={`https://wa.me/${DUTY_OFFICER.whatsapp}?text=${encodeURIComponent(
                  `🚨 Naval Anchorage SafeCity ALERT\n${criticalAlert.event} — CAM ${criticalAlert.cameraIndex}\nZone: ${criticalAlert.zone}\nTime: ${criticalAlert.clockLabel}`,
                )}`}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => blip()}
                className="w-full text-xs font-bold py-2.5 px-4 rounded-xl flex items-center justify-center gap-2 bg-emerald-500/15 border border-emerald-600/30 text-emerald-800 dark:text-emerald-400 hover:bg-emerald-500/25 hover:border-emerald-600/50 transition-all shadow-sm group"
                title={`Notify ${DUTY_OFFICER.name} via WhatsApp`}
              >
                <MessageCircle className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400 group-hover:scale-110 transition-transform" />
                <span className="truncate">Notify {DUTY_OFFICER.name} via WhatsApp</span>
                <ExternalLink className="h-3.5 w-3.5 shrink-0 opacity-70" />
              </a>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-slate-200 dark:border-[#293B52] bg-white dark:bg-[#111D2E] px-6 py-4 flex gap-3">
          <button
            onClick={focusStream}
            className="flex-1 flex items-center justify-center gap-2 rounded-xl border border-blue-600/40 dark:border-cyan/50 bg-blue-600/10 dark:bg-cyan/15 px-4 py-2.5 text-xs font-bold text-blue-700 dark:text-cyan transition-all hover:bg-blue-600/20 dark:hover:bg-cyan/25 active:scale-95 whitespace-nowrap shadow-sm"
            title="Move this camera to the primary tile and close the alert"
          >
            <Focus className="h-4 w-4 shrink-0" />
            <span>FOCUS STREAM</span>
          </button>
          <button
            onClick={acknowledgeAlert}
            className="flex-1 flex items-center justify-center gap-2 rounded-xl border border-amber-600/40 dark:border-amber-500/50 bg-amber-500/15 dark:bg-amber-500/20 px-4 py-2.5 text-xs font-bold text-amber-800 dark:text-amber-300 transition-all hover:bg-amber-500/25 dark:hover:bg-amber-500/30 active:scale-95 whitespace-nowrap shadow-sm"
            title="Acknowledge & close"
          >
            <span>ACKNOWLEDGE</span>
          </button>
        </div>
      </div>
    </div>
  )
}
