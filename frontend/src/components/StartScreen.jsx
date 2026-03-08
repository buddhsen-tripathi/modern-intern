const GESTURES = [
  { icon: '\u270B', label: 'Note' },
  { icon: '\u270C\uFE0F', label: 'Email' },
  { icon: '\u261D\uFE0F', label: 'Calendar' },
  { icon: '\uD83D\uDC4B', label: 'Meeting' },
  { icon: '\uD83D\uDC4C', label: 'Send' },
  { icon: '\uD83D\uDC4D', label: 'Confirm' },
]

const VOICE_COMMANDS = [
  { cmd: '"take note"', desc: 'Start dictating a note' },
  { cmd: '"note end"', desc: 'Save the note' },
]

export default function StartScreen({ phase, onStart }) {
  const isStarting = phase === 'starting'

  return (
    <div className="start-screen">
      <div className="start-content">
        <div className="start-logo">
          <div className="logo-icon">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <path d="M12 16v-4M12 8h.01" />
            </svg>
          </div>
          <div className="start-title">SILAS</div>
          <div className="start-subtitle">PERSONAL ASSISTANT</div>
        </div>

        <button className="btn-primary" disabled={isStarting} onClick={onStart}>
          {isStarting ? 'STARTING...' : 'START'}
        </button>
        <div className="start-hint">
          {isStarting ? 'grant camera + mic permissions...' : 'camera + mic required'}
        </div>

        <div className="gesture-guide">
          <div className="gesture-guide-title">GESTURES</div>
          <div className="gesture-list">
            {GESTURES.map((g) => (
              <div className="gesture-item" key={g.label}>
                <span className="gesture-icon">{g.icon}</span>
                <span className="gesture-label">{g.label}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="voice-guide">
          <div className="voice-guide-title">VOICE COMMANDS</div>
          <div className="voice-list">
            {VOICE_COMMANDS.map((v) => (
              <div className="voice-item" key={v.cmd}>
                <span className="voice-item-cmd">{v.cmd}</span>
                <span className="voice-item-desc">{v.desc}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
