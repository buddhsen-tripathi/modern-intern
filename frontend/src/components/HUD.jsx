import { useEffect, useRef, useState, useCallback } from 'react'

const ACTION_LABELS = {
  note: 'Note saved',
  note_start: 'Recording note',
  note_stop: 'Note saved',
  meeting_minutes: 'Meeting minutes',
  draft_email: 'Email drafted',
  send_email: 'Email sent',
  read_email: 'Reading email',
  calendar_event: 'Event created',
}

const FEED_ICONS = {
  note: '\uD83D\uDCDD',
  note_start: '\uD83D\uDCDD',
  meeting_minutes: '\uD83D\uDCCB',
  draft_email: '\u2709\uFE0F',
  send_email: '\uD83D\uDCE8',
  read_email: '\uD83D\uDCE9',
  calendar_event: '\uD83D\uDCC5',
}

function formatTime(date) {
  return (
    date.getHours().toString().padStart(2, '0') +
    ':' +
    date.getMinutes().toString().padStart(2, '0')
  )
}

function Toast({ text, type, onDone }) {
  return (
    <div className={`toast toast-${type}`} onAnimationEnd={onDone}>
      {text}
    </div>
  )
}

function FeedEntry({ icon, text, time, onFade }) {
  const [fading, setFading] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setFading(true), 30000)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div
      className={`feed-entry${fading ? ' fading' : ''}`}
      onAnimationEnd={() => {
        if (fading) onFade()
      }}
    >
      <span className="feed-icon">{icon}</span>
      <span className="feed-text">{text}</span>
      <span className="feed-time">{time}</span>
    </div>
  )
}

export default function HUD({ events, narration, vadState, voiceStatus, isPaused, onTogglePause }) {
  const [toasts, setToasts] = useState([])
  const [feed, setFeed] = useState([])
  const [statusLabel, setStatusLabel] = useState('ACTIVE')
  const [isRecording, setIsRecording] = useState(false)
  const lastProcessedRef = useRef(0)

  const addToast = useCallback((text, type) => {
    const id = Date.now() + Math.random()
    setToasts((prev) => [...prev, { id, text, type }])
  }, [])

  const addToFeed = useCallback((action, message) => {
    const id = Date.now() + Math.random()
    const time = formatTime(new Date())
    const icon = FEED_ICONS[action] || '\u2022'
    setFeed((prev) => [...prev.slice(-5), { id, icon, text: message, time }])
  }, [])

  // Process events
  useEffect(() => {
    if (events.length === 0) return
    const latest = events[events.length - 1]
    if (!latest || latest._id <= lastProcessedRef.current) return
    lastProcessedRef.current = latest._id

    const event = latest

    if (event.type === 'action_result') {
      const label = ACTION_LABELS[event.action] || event.action
      const isError = event.status === 'error'
      addToast(event.message || label, isError ? 'error' : 'success')

      if (event.action === 'note_start' && event.status === 'success') {
        setIsRecording(true)
        setStatusLabel('REC NOTE')
      } else if (event.action === 'note' || event.action === 'note_stop') {
        setIsRecording(false)
        setStatusLabel('ACTIVE')
      }

      if (!isError) {
        addToFeed(event.action, event.message || label)
      }
    }
  }, [events, addToast, addToFeed])

  // Update status label when paused
  useEffect(() => {
    if (isPaused) {
      setStatusLabel('PAUSED')
    } else if (!isRecording) {
      setStatusLabel('ACTIVE')
    }
  }, [isPaused, isRecording])

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const removeFeedEntry = useCallback((id) => {
    setFeed((prev) => prev.filter((f) => f.id !== id))
  }, [])

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

      {/* Toasts */}
      <div className="hud-mid">
        <div className="toast-container">
          {toasts.map((t) => (
            <Toast key={t.id} text={t.text} type={t.type} onDone={() => removeToast(t.id)} />
          ))}
        </div>
      </div>

      {/* Bottom */}
      <div className="hud-bottom">
        <div className="activity-feed">
          {feed.map((f) => (
            <FeedEntry
              key={f.id}
              icon={f.icon}
              text={f.text}
              time={f.time}
              onFade={() => removeFeedEntry(f.id)}
            />
          ))}
        </div>

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
