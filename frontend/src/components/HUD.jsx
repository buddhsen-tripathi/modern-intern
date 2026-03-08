import { useEffect, useRef, useState, useCallback } from 'react'

const ACTION_LABELS = {
  note: 'NOTE SAVED',
  note_start: 'NOTE REC STARTED',
  note_stop: 'NOTE SAVED',
  meeting_minutes: 'MEETING MINUTES',
  draft_email: 'EMAIL DRAFTED',
  send_email: 'EMAIL SENT',
  read_email: 'EMAIL READ',
  calendar_event: 'EVENT CREATED',
}

const LOG_PREFIXES = {
  note: 'NOTE',
  note_start: 'NOTE',
  note_stop: 'NOTE',
  meeting_minutes: 'MEET',
  draft_email: 'MAIL',
  send_email: 'MAIL',
  read_email: 'MAIL',
  calendar_event: 'CAL',
}

function formatTimestamp(date) {
  return (
    date.getHours().toString().padStart(2, '0') +
    ':' +
    date.getMinutes().toString().padStart(2, '0') +
    ':' +
    date.getSeconds().toString().padStart(2, '0')
  )
}

function LogEntry({ entry }) {
  const levelClass = entry.level || 'info'
  return (
    <div className={`log-line log-${levelClass}`}>
      <span className="log-ts">{entry.ts}</span>
      <span className="log-tag">[{entry.tag}]</span>
      <span className="log-msg">{entry.text}</span>
    </div>
  )
}

export default function HUD({ events, narration, vadState, voiceStatus, isPaused, onTogglePause }) {
  const [logs, setLogs] = useState(() => [
    { id: 0, ts: formatTimestamp(new Date()), tag: 'SYS', text: 'SILAS v2.0 — voice-only mode', level: 'system' },
    { id: 1, ts: formatTimestamp(new Date()), tag: 'SYS', text: 'Awaiting session start...', level: 'muted' },
  ])
  const [statusLabel, setStatusLabel] = useState('ACTIVE')
  const [isRecording, setIsRecording] = useState(false)
  const lastProcessedRef = useRef(0)
  const logIdRef = useRef(2)
  const logEndRef = useRef(null)
  const prevVadRef = useRef(null)
  const prevPausedRef = useRef(isPaused)

  const addLog = useCallback((tag, text, level = 'info') => {
    const id = logIdRef.current++
    const ts = formatTimestamp(new Date())
    setLogs((prev) => [...prev.slice(-80), { id, ts, tag, text, level }])
  }, [])

  // Auto-scroll log
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  // Process events
  useEffect(() => {
    if (events.length === 0) return
    const latest = events[events.length - 1]
    if (!latest || latest._id <= lastProcessedRef.current) return
    lastProcessedRef.current = latest._id

    const event = latest

    if (event.type === 'action_result') {
      const label = ACTION_LABELS[event.action] || event.action.toUpperCase()
      const tag = LOG_PREFIXES[event.action] || 'ACT'
      const isError = event.status === 'error'

      if (isError) {
        addLog(tag, `ERR: ${event.message || label}`, 'error')
      } else {
        addLog(tag, event.message || label, 'success')
      }

      if (event.action === 'note_start' && event.status === 'success') {
        setIsRecording(true)
        setStatusLabel('REC NOTE')
      } else if (event.action === 'note' || event.action === 'note_stop') {
        setIsRecording(false)
        setStatusLabel('ACTIVE')
      }
    }
  }, [events, addLog])

  // Log narration
  useEffect(() => {
    if (narration && narration.trim()) {
      addLog('SILAS', narration, 'narration')
    }
  }, [narration, addLog])

  // Log VAD state changes
  useEffect(() => {
    if (vadState && vadState !== prevVadRef.current) {
      prevVadRef.current = vadState
      if (vadState === 'LISTENING') {
        addLog('MIC', 'Voice activity detected — listening', 'info')
      } else if (vadState === 'IDLE') {
        addLog('MIC', 'Silence detected — idle', 'muted')
      }
    }
  }, [vadState, addLog])

  // Log pause/resume
  useEffect(() => {
    if (isPaused !== prevPausedRef.current) {
      prevPausedRef.current = isPaused
      if (isPaused) {
        setStatusLabel('PAUSED')
        addLog('SYS', 'Session paused', 'warn')
      } else if (!isRecording) {
        setStatusLabel('ACTIVE')
        addLog('SYS', 'Session resumed', 'system')
      }
    }
  }, [isPaused, isRecording, addLog])

  const micListening = vadState === 'LISTENING'

  return (
    <div className="hud">
      {/* Top bar */}
      <div className="hud-top">
        <div>
          <div className={`status-pill${isRecording ? ' recording' : ''}${isPaused ? ' paused' : ''}`}>
            <div className="status-dot" />
            <span>{statusLabel}</span>
          </div>
        </div>
        <div>
          <button
            className={`pause-btn${isPaused ? ' paused' : ''}`}
            onClick={onTogglePause}
          >
            {isPaused ? 'RESUME' : 'PAUSE'}
          </button>
        </div>
      </div>

      {/* Terminal log */}
      <div className="terminal-wrap">
        <div className="terminal-header">
          <span className="terminal-title">SILAS // SYSTEM LOG</span>
          <span className="terminal-count">{logs.length} entries</span>
        </div>
        <div className="terminal-body">
          {logs.map((entry) => (
            <LogEntry key={entry.id} entry={entry} />
          ))}
          <div ref={logEndRef} />
        </div>
      </div>

      {/* Bottom */}
      <div className="hud-bottom">
        <div className="narration-bar">
          <div className="narration-indicator">
            <div className={`mic-indicator${micListening ? ' listening' : ''}`} />
            <span className="narration-label">SILAS</span>
          </div>
          <div className="narration-text">{narration}</div>
          <div className={`voice-status${voiceStatus ? ` ${voiceStatus}` : ''}`}>
            {voiceStatus === 'listening'
              ? 'LISTENING'
              : voiceStatus === 'active'
                ? 'VOICE'
                : voiceStatus === 'no-mic'
                  ? 'NO MIC'
                  : ''}
          </div>
        </div>
      </div>
    </div>
  )
}
