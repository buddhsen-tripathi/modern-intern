import { useRef, useCallback } from 'react'
import useSilas from './hooks/useSilas'
import StartScreen from './components/StartScreen'
import HUD from './components/HUD'

export default function App() {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const { phase, narration, vadState, voiceStatus, events, start } = useSilas()

  const handleStart = useCallback(() => {
    start(videoRef.current, canvasRef.current)
  }, [start])

  return (
    <>
      {/* Camera layer — always present */}
      <div className="camera-layer">
        <video ref={videoRef} autoPlay playsInline muted />
        <canvas ref={canvasRef} />
      </div>

      {/* Start screen */}
      {phase !== 'active' && <StartScreen phase={phase} onStart={handleStart} />}

      {/* HUD overlay */}
      {phase === 'active' && (
        <HUD
          events={events}
          narration={narration}
          vadState={vadState}
          voiceStatus={voiceStatus}
        />
      )}
    </>
  )
}
