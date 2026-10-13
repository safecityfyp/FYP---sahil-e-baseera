import { Check, ExternalLink, MessageCircle, X } from 'lucide-react'
import { useApp } from '../../store/AppContext'
import { DUTY_OFFICER, SEVERITY_META } from '../../constants'
import { blip } from '../../lib/audio'
import type { Toast } from '../../types'

function waLink(t: Toast): string {
  const label = t.severity === 'medium' ? '⚠️ WARNING' : 'ℹ️ ADVISORY'
  const msg = `${label} — Naval Anchorage SafeCity\n${t.title}\n${t.detail}\n${t.cameraLabel}`
  return `https://wa.me/${DUTY_OFFICER.whatsapp}?text=${encodeURIComponent(msg)}`
}

export default function ToastStack() {
  const { toasts, dismissToast, acknowledgeIncident } = useApp()

  const handleAcknowledge = (t: Toast) => {
    acknowledgeIncident(t.incidentId)
    dismissToast(t.id)
  }

  if (toasts.length === 0) return null

  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col-reverse gap-3 pointer-events-auto max-w-[340px] w-full">
      {toasts.map((t) => {
        const sev = SEVERITY_META[t.severity]
        const isMedium = t.severity === 'medium'
        const isHigh = t.severity === 'high'

        // Theme-responsive title color
        const titleColorClass = isHigh
          ? 'text-rose-600 dark:text-rose-400'
          : isMedium
          ? 'text-amber-600 dark:text-amber-400'
          : 'text-blue-600 dark:text-cyan'

        // Theme-responsive border accent
        const borderClass = isHigh
          ? 'border-l-4 border-l-rose-500'
          : isMedium
          ? 'border-l-4 border-l-amber-500'
          : 'border-l-4 border-l-blue-500'

        return (
          <div
            key={t.id}
            className={`animate-toast-in w-full rounded-xl border border-slate-200 dark:border-[#293B52] bg-white dark:bg-[#17263A] shadow-2xl transition-all ${borderClass}`}
            style={{
              boxShadow: '0 12px 28px rgba(0,0,0,0.18), 0 2px 8px rgba(0,0,0,0.08)',
            }}
          >
            {/* Main Content Body */}
            <div className="flex items-start gap-3 p-3.5 pb-2.5">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <div
                    className="h-2 w-2 rounded-full flex-shrink-0 animate-pulse"
                    style={{ backgroundColor: sev.color }}
                  />
                  <span className={`font-bold text-xs leading-snug truncate ${titleColorClass}`}>
                    {t.title}
                  </span>
                </div>
                <p className="text-xs text-slate-700 dark:text-slate-300 font-medium mb-1.5 leading-relaxed">
                  {t.detail}
                </p>
                <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                  {t.cameraLabel}
                </div>
              </div>

              {/* Dismiss button */}
              <button
                onClick={() => dismissToast(t.id)}
                className="flex-shrink-0 p-1 rounded-md text-slate-400 hover:text-slate-700 dark:hover:text-white transition"
                title="Dismiss"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>

            {/* Action Buttons Row */}
            <div className="flex items-center gap-2 border-t border-slate-200 dark:border-[#293B52] bg-slate-50 dark:bg-[#111D2E] px-3 py-2 rounded-b-xl">
              <a
                href={waLink(t)}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => blip()}
                className="flex flex-1 items-center justify-center gap-1 rounded-lg border border-emerald-600/30 bg-emerald-500/10 dark:bg-green-900/30 px-2.5 py-1.5 text-[10px] font-bold text-emerald-700 dark:text-emerald-400 hover:bg-emerald-500/20 dark:hover:bg-green-900/50 transition"
                title="Notify duty officer via WhatsApp"
              >
                <MessageCircle className="h-3 w-3" />
                <span>WhatsApp</span>
                <ExternalLink className="h-2.5 w-2.5 opacity-60 ml-0.5" />
              </a>
              <button
                onClick={() => handleAcknowledge(t)}
                className="flex flex-1 items-center justify-center gap-1 rounded-lg border border-blue-600/30 dark:border-cyan/40 bg-blue-600/10 dark:bg-cyan/10 px-2.5 py-1.5 text-[10px] font-bold text-blue-700 dark:text-cyan hover:bg-blue-600/20 dark:hover:bg-cyan/20 transition"
                title="Acknowledge event"
              >
                <Check className="h-3 w-3" />
                <span>Acknowledge</span>
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}
