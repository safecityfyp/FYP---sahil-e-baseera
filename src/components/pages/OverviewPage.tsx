import {
  ShieldAlert,
  Video,
  Cpu,
  Layers,
  Activity,
  HardDrive,
  Car,
  Users,
  AlertTriangle,
  Route,
  ArrowRight,
  TrendingUp,
  CheckCircle2,
} from 'lucide-react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from 'recharts'
import { useApp } from '../../store/AppContext'

// Sample 24-hour activity flow data
const TIMELINE_DATA = [
  { hour: '00:00', traffic: 12, violations: 2, safety: 0 },
  { hour: '02:00', traffic: 8, violations: 1, safety: 0 },
  { hour: '04:00', traffic: 5, violations: 0, safety: 0 },
  { hour: '06:00', traffic: 28, violations: 4, safety: 1 },
  { hour: '08:00', traffic: 84, violations: 14, safety: 2 },
  { hour: '10:00', traffic: 112, violations: 18, safety: 3 },
  { hour: '12:00', traffic: 95, violations: 12, safety: 1 },
  { hour: '14:00', traffic: 128, violations: 22, safety: 4 },
  { hour: '16:00', traffic: 145, violations: 26, safety: 2 },
  { hour: '18:00', traffic: 160, violations: 31, safety: 5 },
  { hour: '20:00', traffic: 118, violations: 19, safety: 1 },
  { hour: '22:00', traffic: 64, violations: 8, safety: 0 },
]

// Donut composition
const DONUT_DATA = [
  { name: 'Traffic & Speed', value: 52, color: '#16B8D4' },
  { name: 'Critical Safety', value: 24, color: '#EF4444' },
  { name: 'Person Behaviour', value: 14, color: '#F59E0B' },
  { name: 'Multi-Cam Tracking', value: 10, color: '#A855F7' },
]

export default function OverviewPage() {
  const { setTab, hardware, incidents, cameras } = useApp()


  return (
    <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6 select-none transition-colors">
      {/* 1. Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-edge2/40 pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
            <span className="p-2 rounded-xl bg-gold/10 border border-gold/30 text-gold-soft flex items-center justify-center">
              <ShieldAlert className="h-6 w-6" />
            </span>
            SafeCity AI Command & Telemetry Center
          </h1>
          <p className="text-xs sm:text-sm text-slate-400 mt-1">
            Real-time multi-lane traffic surveillance, 12 specialized deep learning models, automated enforcement, and hardware telemetry.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => setTab('wall')}
            className="btn gap-2 bg-cyan/15 border-cyan/40 text-cyan hover:border-cyan hover:bg-cyan/25"
          >
            <Video className="h-4 w-4" />
            <span>Open Live Wall</span>
          </button>
          <button
            onClick={() => setTab('models')}
            className="btn gap-2 bg-gold/15 border-gold/40 text-gold-soft hover:border-gold hover:bg-gold/25"
          >
            <Layers className="h-4 w-4" />
            <span>Explore 12 AI Models</span>
          </button>
        </div>
      </div>

      {/* 2. Hardware & Inference Engine Specs Panel (From FYP-Copy Sentinel) */}
      <section className="card p-5 border-edge2/60 bg-surface/90">
        <div className="flex items-center justify-between pb-3 border-b border-edge2/40">
          <div className="flex items-center gap-2.5">
            <Cpu className="h-5 w-5 text-cyan" />
            <h2 className="text-xs font-bold text-white uppercase tracking-wider hud-label">
              Hardware Engine & GPU Telemetry
            </h2>
          </div>
          <span className="pill border-emerald-500/30 bg-emerald-500/10 text-emerald-400 font-mono text-[10px]">
            CUDA ACCELERATED
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mt-4">
          {/* CPU Tile */}
          <div className="p-4 rounded-xl bg-surface2/50 border border-edge2/50 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-400">
                <span>CPU Processor</span>
                <Cpu className="h-4 w-4 text-cyan" />
              </div>
              <div className="text-xs text-slate-400 mt-1.5 truncate" title={hardware.cpu.model}>
                {hardware.cpu.model}
              </div>
              <div className="text-2xl font-bold font-mono text-cyan mt-1">
                {hardware.cpu.percent}%
              </div>
            </div>
            <div className="mt-3 h-1.5 rounded-full bg-slate-700/50 overflow-hidden">
              <div
                className="h-full rounded-full bg-cyan transition-all duration-700"
                style={{ width: `${hardware.cpu.percent}%` }}
              />
            </div>
          </div>

          {/* GPU Tile */}
          <div className="p-4 rounded-xl bg-surface2/50 border border-edge2/50 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-400">
                <span>GPU Acceleration</span>
                <Activity className="h-4 w-4 text-emerald-400" />
              </div>
              <div className="text-xs text-slate-400 mt-1.5 truncate" title={hardware.gpu.model}>
                {hardware.gpu.model}
              </div>
              <div className="flex items-baseline gap-2 mt-1">
                <span className="text-2xl font-bold font-mono text-emerald-400">
                  {hardware.gpu.utilPercent}%
                </span>
                <span className="text-[11px] font-mono text-slate-500">
                  VRAM {hardware.gpu.vramUsedMb} / {hardware.gpu.vramTotalMb} MB
                </span>
              </div>
            </div>
            <div className="mt-3 h-1.5 rounded-full bg-slate-700/50 overflow-hidden">
              <div
                className="h-full rounded-full bg-emerald-400 transition-all duration-700"
                style={{ width: `${hardware.gpu.utilPercent}%` }}
              />
            </div>
          </div>

          {/* RAM Tile */}
          <div className="p-4 rounded-xl bg-surface2/50 border border-edge2/50 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-400">
                <span>System RAM</span>
                <span className="text-xs font-mono text-gold-soft font-bold">DDR5</span>
              </div>
              <div className="text-xs text-slate-400 mt-1.5">32 GB High-Speed Memory</div>
              <div className="flex items-baseline gap-2 mt-1">
                <span className="text-2xl font-bold font-mono text-gold-soft">
                  {hardware.ram.usedGb} GB
                </span>
                <span className="text-[11px] font-mono text-slate-500">
                  ({hardware.ram.percent}%)
                </span>
              </div>
            </div>
            <div className="mt-3 h-1.5 rounded-full bg-slate-700/50 overflow-hidden">
              <div
                className="h-full rounded-full bg-gold transition-all duration-700"
                style={{ width: `${hardware.ram.percent}%` }}
              />
            </div>
          </div>

          {/* Storage Tile */}
          <div className="p-4 rounded-xl bg-surface2/50 border border-edge2/50 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-400">
                <span>Evidence Storage</span>
                <HardDrive className="h-4 w-4 text-purple-400" />
              </div>
              <div className="text-xs text-slate-400 mt-1.5">NVMe SSD Snapshot Log</div>
              <div className="flex items-baseline gap-2 mt-1">
                <span className="text-2xl font-bold font-mono text-purple-400">
                  {hardware.storage.usedGb} GB
                </span>
                <span className="text-[11px] font-mono text-slate-500">
                  ({hardware.storage.percent}%)
                </span>
              </div>
            </div>
            <div className="mt-3 h-1.5 rounded-full bg-slate-700/50 overflow-hidden">
              <div
                className="h-full rounded-full bg-purple-400 transition-all duration-700"
                style={{ width: `${hardware.storage.percent}%` }}
              />
            </div>
          </div>
        </div>
      </section>

      {/* 3. 4 Operational Model Category Cards */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-bold text-white uppercase tracking-wider hud-label flex items-center gap-2">
            <Layers className="h-4 w-4 text-gold-soft" />
            12 AI Enforcement Modules Across 4 Functional Sectors
          </h2>
          <span className="text-xs text-slate-400 font-medium">All Models Operational</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Category 1: Traffic */}
          <div
            onClick={() => setTab('models')}
            className="card p-4 hover:border-cyan/60 transition cursor-pointer border-edge2/60 bg-gradient-to-br from-cyan-500/10 to-transparent flex flex-col justify-between"
          >
            <div>
              <div className="flex items-center justify-between">
                <div className="p-2 rounded-lg bg-cyan-500/20 text-cyan border border-cyan/30">
                  <Car className="h-5 w-5" />
                </div>
                <span className="pill border-cyan-500/30 bg-cyan-500/10 text-cyan text-[10px]">
                  5 Models
                </span>
              </div>
              <h3 className="font-bold text-white text-base mt-3">Traffic & Vehicles</h3>
              <p className="text-xs text-slate-400 mt-1 line-clamp-2">
                Helmet Violations, ANPR & Make Profiling, Speed Radar, Wrong-Way, and Idle Parking.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-edge2/40 flex items-center justify-between text-xs text-slate-300">
              <span className="font-mono text-cyan">187 Detections</span>
              <span className="text-gold-soft hover:underline flex items-center gap-1 font-semibold">
                Explore <ArrowRight className="h-3.5 w-3.5" />
              </span>
            </div>
          </div>

          {/* Category 2: Person Behaviour */}
          <div
            onClick={() => setTab('models')}
            className="card p-4 hover:border-amber-400/60 transition cursor-pointer border-edge2/60 bg-gradient-to-br from-amber-500/10 to-transparent flex flex-col justify-between"
          >
            <div>
              <div className="flex items-center justify-between">
                <div className="p-2 rounded-lg bg-amber-500/20 text-amber-400 border border-amber-500/30">
                  <Users className="h-5 w-5" />
                </div>
                <span className="pill border-amber-500/30 bg-amber-500/10 text-amber-400 text-[10px]">
                  3 Models
                </span>
              </div>
              <h3 className="font-bold text-white text-base mt-3">Person Behaviour</h3>
              <p className="text-xs text-slate-400 mt-1 line-clamp-2">
                Falling Person & Medical Alert, Mob Gathering (&gt;7 Persons), and Perimeter Wall Breach.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-edge2/40 flex items-center justify-between text-xs text-slate-300">
              <span className="font-mono text-amber-400">4 Alerts Active</span>
              <span className="text-gold-soft hover:underline flex items-center gap-1 font-semibold">
                Explore <ArrowRight className="h-3.5 w-3.5" />
              </span>
            </div>
          </div>

          {/* Category 3: Critical Safety */}
          <div
            onClick={() => setTab('models')}
            className="card p-4 hover:border-rose-500/60 transition cursor-pointer border-edge2/60 bg-gradient-to-br from-rose-500/10 to-transparent flex flex-col justify-between"
          >
            <div>
              <div className="flex items-center justify-between">
                <div className="p-2 rounded-lg bg-rose-500/20 text-rose-400 border border-rose-500/30">
                  <AlertTriangle className="h-5 w-5" />
                </div>
                <span className="pill border-rose-500/30 bg-rose-500/10 text-rose-400 text-[10px]">
                  2 Models
                </span>
              </div>
              <h3 className="font-bold text-white text-base mt-3">Critical Safety</h3>
              <p className="text-xs text-slate-400 mt-1 line-clamp-2">
                Smoke & Fire Luminescence Detection and Multi-Vehicle Impact Crash Alerts.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-edge2/40 flex items-center justify-between text-xs text-slate-300">
              <span className="font-mono text-rose-400">3 Emergencies</span>
              <span className="text-gold-soft hover:underline flex items-center gap-1 font-semibold">
                Explore <ArrowRight className="h-3.5 w-3.5" />
              </span>
            </div>
          </div>

          {/* Category 4: Multi-Camera Tracking */}
          <div
            onClick={() => setTab('models')}
            className="card p-4 hover:border-purple-400/60 transition cursor-pointer border-edge2/60 bg-gradient-to-br from-purple-500/10 to-transparent flex flex-col justify-between"
          >
            <div>
              <div className="flex items-center justify-between">
                <div className="p-2 rounded-lg bg-purple-500/20 text-purple-400 border border-purple-500/30">
                  <Route className="h-5 w-5" />
                </div>
                <span className="pill border-purple-500/30 bg-purple-500/10 text-purple-400 text-[10px]">
                  2 Models
                </span>
              </div>
              <h3 className="font-bold text-white text-base mt-3">Multi-Camera Tracking</h3>
              <p className="text-xs text-slate-400 mt-1 line-clamp-2">
                Canonical Re-ID Person Tracking and Cross-Node Vehicle Trajectory Reconstruction.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-edge2/40 flex items-center justify-between text-xs text-slate-300">
              <span className="font-mono text-purple-400">104 Targets</span>
              <span className="text-gold-soft hover:underline flex items-center gap-1 font-semibold">
                Explore <ArrowRight className="h-3.5 w-3.5" />
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 4. Visual Analytics Strip (Area Chart + Donut Chart) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* 24-Hour Traffic Flow Chart */}
        <div className="lg:col-span-8 card p-5 border-edge2/60">
          <div className="flex items-center justify-between pb-3 border-b border-edge2/40">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4.5 w-4.5 text-cyan" />
              <h2 className="text-xs font-bold text-white uppercase tracking-wider hud-label">
                24-Hour Traffic Flow & Incident Rate
              </h2>
            </div>
            <span className="text-[10px] font-mono text-slate-400">Live Polling • Society Gates</span>
          </div>

          <div className="h-64 mt-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={TIMELINE_DATA}>
                <defs>
                  <linearGradient id="colorTraffic" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#16B8D4" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#16B8D4" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="colorViolations" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#F59E0B" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#F59E0B" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="hour" stroke="#64748B" fontSize={11} />
                <YAxis stroke="#64748B" fontSize={11} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#17263A',
                    borderColor: '#293B52',
                    borderRadius: '8px',
                    fontSize: '12px',
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="traffic"
                  stroke="#16B8D4"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#colorTraffic)"
                  name="Vehicles Scanned"
                />
                <Area
                  type="monotone"
                  dataKey="violations"
                  stroke="#F59E0B"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#colorViolations)"
                  name="Safety Flags"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Donut Chart */}
        <div className="lg:col-span-4 card p-5 border-edge2/60 flex flex-col justify-between">
          <div className="flex items-center justify-between pb-3 border-b border-edge2/40">
            <h2 className="text-xs font-bold text-white uppercase tracking-wider hud-label">
              Incident Category Composition
            </h2>
            <span className="pill border-rose-500/30 bg-rose-500/10 text-rose-400 text-[10px]">
              Active Split
            </span>
          </div>

          <div className="h-52 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={DONUT_DATA}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={75}
                  paddingAngle={4}
                  dataKey="value"
                >
                  {DONUT_DATA.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#17263A',
                    borderColor: '#293B52',
                    borderRadius: '8px',
                    fontSize: '12px',
                  }}
                />
                <Legend
                  wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }}
                  formatter={(val) => <span className="text-slate-300">{val}</span>}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* 5. Live Security Event Feed & Aggregate KPI Strip */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Real-Time Live Security Event Feed */}
        <div className="lg:col-span-7 card p-5 border-edge2/60 flex flex-col h-[380px]">
          <div className="flex items-center justify-between pb-3 border-b border-edge2/40">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-red-400 animate-ping" />
              <h2 className="text-xs font-bold text-white uppercase tracking-wider hud-label">
                Live Security Event Feed
              </h2>
            </div>
            <span className="pill border-cyan/40 bg-cyan/10 text-cyan text-[10px]">
              LIVE DISPATCH SYNC
            </span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 mt-3 pr-1">
            {incidents.slice(0, 10).map((inc) => (
              <div
                key={inc.id}
                className="p-3 rounded-xl bg-surface2/40 border border-edge2/40 hover:border-steel/60 transition flex items-center justify-between gap-3 text-xs"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div
                    className={`w-2 h-2 rounded-full shrink-0 ${
                      inc.severity === 'high'
                        ? 'bg-rose-500 shadow-glow-red'
                        : inc.severity === 'medium'
                        ? 'bg-amber-400 shadow-glow-amber'
                        : 'bg-cyan'
                    }`}
                  />
                  <div className="min-w-0 truncate">
                    <div className="font-bold text-white truncate flex items-center gap-2">
                      <span>{inc.event}</span>
                      <span className="text-[10px] text-slate-500 font-mono">
                        [{inc.cameraName}]
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-400 truncate mt-0.5">{inc.detail}</div>
                  </div>
                </div>

                <div className="text-right shrink-0 font-mono">
                  <div className="text-[11px] font-bold text-gold-soft">{inc.confidence}% Conf</div>
                  <div className="text-[10px] text-slate-500">{inc.clockLabel}</div>
                </div>
              </div>
            ))}

            {incidents.length === 0 && (
              <div className="text-center text-slate-500 py-16 text-sm">
                Waiting for live security events across cameras...
              </div>
            )}
          </div>
        </div>

        {/* Aggregate KPI Strip */}
        <div className="lg:col-span-5 grid grid-cols-2 gap-4">
          <div className="card p-4 border-l-4 border-l-cyan flex flex-col justify-between">
            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
              SURVEILLANCE FEEDS
            </div>
            <div className="text-3xl font-bold font-mono text-cyan mt-2">
              {cameras.length} / {cameras.length}
            </div>
            <div className="text-xs text-green-400 flex items-center gap-1.5 mt-2">
              <CheckCircle2 className="h-3.5 w-3.5" /> All Feeds Active
            </div>
          </div>

          <div className="card p-4 border-l-4 border-l-gold-soft flex flex-col justify-between">
            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
              SCANNED PLATES
            </div>
            <div className="text-3xl font-bold font-mono text-gold-soft mt-2">148+</div>
            <div className="text-xs text-slate-400 mt-2">fast-plate-ocr Active</div>
          </div>

          <div className="card p-4 border-l-4 border-l-rose-500 flex flex-col justify-between">
            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
              SAFETY VIOLATIONS
            </div>
            <div className="text-3xl font-bold font-mono text-rose-500 mt-2">
              {incidents.length}
            </div>
            <div className="text-xs text-rose-400 mt-2">Today's Total Events</div>
          </div>

          <div className="card p-4 border-l-4 border-l-emerald-400 flex flex-col justify-between">
            <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
              AVG ACCURACY
            </div>
            <div className="text-3xl font-bold font-mono text-emerald-400 mt-2">95.4%</div>
            <div className="text-xs text-emerald-400 mt-2">NVIDIA GPU Accelerated</div>
          </div>
        </div>
      </div>
    </div>
  )
}
