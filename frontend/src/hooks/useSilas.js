import { useCallback, useEffect, useRef, useState } from 'react'

const TAG_MIC = 0x02
const TAG_NARRATION = 0x01
const NARRATION_RATE = 24000

export default function useSilas() {
  const [phase, setPhase] = useState('idle') // idle | starting | active | paused
  const [narration, setNarration] = useState('Listening...')
  const [vadState, setVadState] = useState(null)
  const [voiceStatus, setVoiceStatus] = useState(null)
  const [events, setEvents] = useState([])

  const wsRef = useRef(null)
  const audioCtxRef = useRef(null)
  const narrationGainRef = useRef(null)
  const narrationNextTimeRef = useRef(0)
  const micStreamRef = useRef(null)
  const narrationTimerRef = useRef(null)
  const phaseRef = useRef('idle')

  // Keep phaseRef in sync
  useEffect(() => {
    phaseRef.current = phase
  }, [phase])

  const emitEvent = useCallback((evt) => {
    setEvents((prev) => [...prev.slice(-20), { ...evt, _id: Date.now() + Math.random() }])
  }, [])

  // -- Audio playback --
  const initAudio = useCallback(() => {
    const ctx = new AudioContext()
    const gain = ctx.createGain()
    gain.gain.value = 1.0
    gain.connect(ctx.destination)
    audioCtxRef.current = ctx
    narrationGainRef.current = gain
    narrationNextTimeRef.current = 0
  }, [])

  const playNarrationChunk = useCallback((int16Array) => {
    const ctx = audioCtxRef.current
    if (!ctx || ctx.state === 'closed') return
    const len = int16Array.length
    if (len === 0) return

    const buffer = ctx.createBuffer(1, len, NARRATION_RATE)
    const channel = buffer.getChannelData(0)
    for (let i = 0; i < len; i++) {
      channel[i] = int16Array[i] / 32768
    }

    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(narrationGainRef.current)

    const now = ctx.currentTime
    const start = Math.max(now, narrationNextTimeRef.current)
    source.start(start)
    narrationNextTimeRef.current = start + buffer.duration
  }, [])

  // -- Mic --
  const startMic = useCallback(async () => {
    const ctx = audioCtxRef.current
    if (!ctx) return

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      micStreamRef.current = stream
      await ctx.audioWorklet.addModule('/mic-processor.js')
      const source = ctx.createMediaStreamSource(stream)
      const worklet = new AudioWorkletNode(ctx, 'mic-processor')

      worklet.port.onmessage = (e) => {
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
        const pcm = new Uint8Array(e.data)
        const tagged = new Uint8Array(1 + pcm.byteLength)
        tagged[0] = TAG_MIC
        tagged.set(pcm, 1)
        wsRef.current.send(tagged.buffer)
      }

      source.connect(worklet)
      setVoiceStatus('active')
    } catch (err) {
      console.warn('Mic not available:', err)
      setVoiceStatus('no-mic')
    }
  }, [])

  // -- WebSocket message handlers --
  const handleJSON = useCallback(
    (msg) => {
      switch (msg.type) {
        case 'event':
          emitEvent(msg.data)
          break
        case 'narration':
          setNarration(msg.text)
          clearTimeout(narrationTimerRef.current)
          narrationTimerRef.current = setTimeout(() => setNarration('Listening...'), 10000)
          break
        case 'vad_state':
          setVadState(msg.state)
          if (msg.state === 'LISTENING') {
            setVoiceStatus('listening')
          } else if (micStreamRef.current) {
            setVoiceStatus('active')
          }
          break
      }
    },
    [emitEvent],
  )

  const handleBinary = useCallback(
    (data) => {
      if (data.byteLength < 2) return
      const view = new Uint8Array(data)
      const tag = view[0]
      const pcm = view.slice(1)
      const int16 = new Int16Array(pcm.buffer, pcm.byteOffset, pcm.byteLength / 2)
      if (tag === TAG_NARRATION) {
        playNarrationChunk(int16)
      }
    },
    [playNarrationChunk],
  )

  // -- Connect WebSocket --
  const connectWS = useCallback(() => {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${location.host}/ws`)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      console.log('[WS] Connected')
      ws.send(JSON.stringify({ type: 'start' }))
      setPhase('active')
    }

    ws.onmessage = (e) => {
      if (typeof e.data === 'string') {
        handleJSON(JSON.parse(e.data))
      } else {
        handleBinary(e.data)
      }
    }

    ws.onclose = () => {
      console.log('[WS] Disconnected')
      const p = phaseRef.current
      if (p === 'active' || p === 'paused') {
        setTimeout(connectWS, 2000)
      }
    }

    ws.onerror = (err) => console.error('[WS] Error', err)
  }, [handleJSON, handleBinary])

  // -- Start --
  const start = useCallback(async () => {
    setPhase('starting')

    initAudio()
    await startMic()
    connectWS()
  }, [initAudio, startMic, connectWS])

  // -- Toggle pause/resume --
  const togglePause = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    if (phase === 'active') {
      wsRef.current.send(JSON.stringify({ type: 'stop' }))
      setPhase('paused')
      setNarration('Paused')
    } else if (phase === 'paused') {
      wsRef.current.send(JSON.stringify({ type: 'start' }))
      setPhase('active')
      setNarration('Listening...')
    }
  }, [phase])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close()
      if (audioCtxRef.current) audioCtxRef.current.close()
      if (micStreamRef.current) {
        micStreamRef.current.getTracks().forEach((t) => t.stop())
      }
    }
  }, [])

  return {
    phase,
    narration,
    vadState,
    voiceStatus,
    events,
    start,
    togglePause,
  }
}
