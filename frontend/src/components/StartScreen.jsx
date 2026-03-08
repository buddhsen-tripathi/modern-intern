const VOICE_COMMANDS = [
  { cmd: '"take note"', desc: 'Start dictating a note' },
  { cmd: '"note end"', desc: 'Save the note' },
  { cmd: '"draft email"', desc: 'Draft an email' },
  { cmd: '"send email"', desc: 'Send drafted email' },
  { cmd: '"calendar event"', desc: 'Create a calendar event' },
  { cmd: '"start meeting"', desc: 'Begin recording meeting' },
  { cmd: '"stop meeting"', desc: 'End and save meeting notes' },
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
          <div className="start-title">MODERN INTERN</div>
          <div className="start-subtitle">VOICE ASSISTANT</div>
        </div>

        <button className="btn-primary" disabled={isStarting} onClick={onStart}>
          {isStarting ? 'STARTING...' : 'START'}
        </button>
        <div className="start-hint">
          {isStarting ? 'grant mic permission...' : 'microphone required'}
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
