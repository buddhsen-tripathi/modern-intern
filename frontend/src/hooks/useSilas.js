import { useCallback, useEffect, useRef, useState } from 'react'

const TAG_CAMERA = 0x01
const TAG_MIC = 0x02
const TAG_NARRATION = 0x01
const NARRATION_RATE = 24000

export default function useSilas() {
  const [phase, setPhase] = useState('idle') // idle | starting | active
  const [narration, setNarration] = useState('Listening...')
  const [vadState, setVadState] = useState(null)
  const [voiceStatus, setVoiceStatus] = useState(null) // null | 'active' | 'listening' | 'no-mic'
  const [events, setEvents] = useState([]) // raw events for HUD to process

  const wsRef = useRef(null)
  const audioCtxRef = useRef(null)
  const narrationGainRef = useRef(null)
  const narrationNextTimeRef = useRef(0)
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const capturingRef = useRef(false)
  const micStreamRef = useRef(null)
  const narrationTimerRef = useRef(null)

  // -- Emit event for HUD consumption --
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

  // -- Camera capture --
  const startCamera = useCallback(async (videoEl) => {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 640 }, height: { ideal: 640 } },
      audio: false,
    })
    videoEl.srcObject = stream
    await videoEl.play()
  }, [])

  const captureLoop = useCallback(() => {
    if (!capturingRef.current || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return

    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas) return

    const ctx = canvas.getContext('2d')
    const vw = video.videoWidth
    const vh = video.videoHeight
    const size = Math.min(vw, vh)
    canvas.width = 400
    canvas.height = 400
    ctx.drawImage(video, (vw - size) / 2, (vh - size) / 2, size, size, 0, 0, 400, 400)

    canvas.toBlob(
      (blob) => {
        if (blob && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          blob.arrayBuffer().then((buf) => {
            const tagged = new Uint8Array(1 + buf.byteLength)
            tagged[0] = TAG_CAMERA
            tagged.set(new Uint8Array(buf), 1)
            wsRef.current.send(tagged.buffer)
          })
        }
        setTimeout(captureLoop, 1000)
      },
      'image/jpeg',
      0.7,
    )
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
      capturingRef.current = true
      captureLoop()
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
      if (capturingRef.current) {
        setTimeout(connectWS, 2000)
      }
    }

    ws.onerror = (err) => console.error('[WS] Error', err)
  }, [captureLoop, handleJSON, handleBinary])

  // -- Start --
  const start = useCallback(
    async (videoEl, canvasEl) => {
      videoRef.current = videoEl
      canvasRef.current = canvasEl
      setPhase('starting')

      try {
        initAudio()
        await startCamera(videoEl)
      } catch (err) {
        alert('Camera access required: ' + err.message)
        setPhase('idle')
        return
      }

      await startMic()
      connectWS()
    },
    [initAudio, startCamera, startMic, connectWS],
  )

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      capturingRef.current = false
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
  }
}
