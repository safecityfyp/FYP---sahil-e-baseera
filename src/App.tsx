import { AppProvider, useApp } from './store/AppContext'
import TopBar from './components/TopBar'
import Sidebar from './components/Sidebar'
import OverviewPage from './components/pages/OverviewPage'
import LiveWall from './components/pages/LiveWall'
import TacticalMap from './components/pages/TacticalMap'
import ModelsHub from './components/pages/ModelsHub'
import ForensicPanel from './components/forensics/ForensicPanel'
import TrajectorySearch from './components/pages/TrajectorySearch'
import IncidentLog from './components/pages/IncidentLog'
import CameraManagement from './components/pages/CameraManagement'
import CriticalAlert from './components/alerts/CriticalAlert'
import ToastStack from './components/alerts/ToastStack'

function MainContent() {
  const { tab, forensicCameraId } = useApp()

  switch (tab) {

    case 'wall':
      return <LiveWall />
    case 'map':
      return <TacticalMap />
    case 'overview':
      return <OverviewPage />
    case 'models':
      return <ModelsHub />
    case 'forensics':
      return (
        <div className="flex-1 p-6 overflow-y-auto">
          <ForensicPanel
            cameraId={forensicCameraId || 'CAM-01'}
            onClose={() => { }}
          />
        </div>
      )
    case 'trajectory':
      return <TrajectorySearch />
    case 'incidents':
      return <IncidentLog />
    case 'cameras':
      return <CameraManagement />
    default:
      return <OverviewPage />
  }
}

function GlobalOverlays() {
  const { forensicCameraId, closeForensic, tab } = useApp()
  return (
    <>
      {forensicCameraId && tab !== 'forensics' && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <ForensicPanel cameraId={forensicCameraId} onClose={closeForensic} />
        </div>
      )}
      {tab === 'wall' && <CriticalAlert />}
      <ToastStack />
    </>
  )
}

export default function App() {
  return (
    <AppProvider>
      <div className="flex h-screen w-screen flex-col overflow-hidden bg-base text-slate-200 select-none">
        <TopBar />
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <Sidebar />
          <MainContent />
        </div>
        <GlobalOverlays />
      </div>
    </AppProvider>
  )
}
