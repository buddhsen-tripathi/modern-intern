import { useCallback } from 'react'
import useSilas from './hooks/useSilas'
import StartScreen from './components/StartScreen'
import HUD from './components/HUD'

export default function App() {
  const { phase, narration, vadState, voiceStatus, events, start, togglePause } = useSilas()

  const handleStart = useCallback(() => {
    start()
  }, [start])

  const isActive = phase === 'active' || phase === 'paused'

  return (
    <>
      {/* Start screen */}
      {!isActive && <StartScreen phase={phase} onStart={handleStart} />}

      {/* HUD overlay */}
      {isActive && (
        <HUD
          events={events}
          narration={narration}
          vadState={vadState}
          voiceStatus={voiceStatus}
          isPaused={phase === 'paused'}
          onTogglePause={togglePause}
        />
      )}
    </>
  )
}
