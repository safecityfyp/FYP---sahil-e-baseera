import {
  Flame,
  ShieldAlert,
  Car,
  ScanLine,
  Users,
  Gauge,
  Bike,
  AlertTriangle,
  ArrowDownCircle,
  Clock,
  Route,
  Compass,
} from 'lucide-react'
import type { ModelCategory } from '../../types'
import { AI_MODELS } from '../../constants'

const ICONS: Record<string, typeof Flame> = {
  helmet: Bike,
  anpr: ScanLine,
  wrongway: Car,
  speed: Gauge,
  parking: Clock,
  falling: ArrowDownCircle,
  mob: Users,
  wallbreach: ShieldAlert,
  fire: Flame,
  accident: AlertTriangle,
  track_person: Route,
  track_vehicle: Compass,
}

const COLOR: Record<ModelCategory, string> = {
  traffic: 'border-cyan-500/50 bg-cyan-500/10 text-cyan-700 dark:text-cyan font-semibold',
  behaviour: 'border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-400 font-semibold',
  safety: 'border-rose-500/50 bg-rose-500/10 text-rose-700 dark:text-rose-400 font-semibold',
  tracking: 'border-purple-500/50 bg-purple-500/10 text-purple-700 dark:text-purple-400 font-semibold',
}

export function modelName(id: string) {
  return AI_MODELS.find((m) => m.id === id)?.name ?? id
}
export function modelShort(id: string) {
  return AI_MODELS.find((m) => m.id === id)?.short ?? id.toUpperCase()
}

export function ModelIcon({ id, className }: { id: string; className?: string }) {
  const Icon = ICONS[id] ?? ShieldAlert
  return <Icon className={className ?? 'h-3.5 w-3.5'} />
}

export default function ModelBadge({ id, size = 'sm' }: { id: string; size?: 'sm' | 'xs' }) {
  const model = AI_MODELS.find((m) => m.id === id)
  const cat = model?.category ?? 'safety'
  const Icon = ICONS[id] ?? ShieldAlert
  return (
    <span
      className={`chip inline-flex items-center gap-1.5 ${COLOR[cat]} ${
        size === 'xs' ? 'px-1.5 py-px text-[9px]' : 'px-2.5 py-0.5 text-xs'
      }`}
      title={model?.name}
    >
      <Icon className={`shrink-0 ${size === 'xs' ? 'h-2.5 w-2.5' : 'h-3.5 w-3.5'}`} />
      <span className="whitespace-nowrap font-medium">{model?.short ?? id}</span>
    </span>
  )
}
