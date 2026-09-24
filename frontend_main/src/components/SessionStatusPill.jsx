const LABELS = {
  idle: 'Idle',
  starting: 'Starting…',
  running: 'Running',
  done: 'Done',
  error: 'Error',
}

export default function SessionStatusPill({ status }) {
  // "starting" visually reads the same as "running" (pulsing dot) - only
  // the label text differs.
  const visualClass = status === 'starting' ? 'running' : status
  return (
    <span className={`session-status-pill ${visualClass}`}>
      <span className="dot" />
      {LABELS[status] || status}
    </span>
  )
}
