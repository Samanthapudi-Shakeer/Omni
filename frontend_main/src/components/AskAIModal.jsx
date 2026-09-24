export default function AskAIModal({ issue, explanation, loading, onClose }) {
  if (!issue) return null
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <h4>{issue.tool} / {issue.rule}</h4>
        <div className="issue-meta" style={{ marginBottom: 12 }}>
          {issue.file}:{issue.line} · {issue.severity}
        </div>
        {loading
          ? <div className="empty-state"><span className="spinner" /> Asking Ollama…</div>
          : <p style={{ fontSize: 13.5, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{explanation}</p>}
      </div>
    </div>
  )
}
