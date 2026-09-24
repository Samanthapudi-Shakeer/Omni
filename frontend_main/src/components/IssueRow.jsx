export default function IssueRow({ issue, onAsk, onHowToFix, fixed, fixDisabled }) {
  return (
    <div className="issue-row">
      <div className={`sev-dot sev-${issue.severity}`} />
      <div className="issue-main">
        <div className="issue-msg">
          {fixed && <span style={{ color: '#1e9e5c', marginRight: 6 }} title="Fixed">✓</span>}
          {issue.message}
        </div>
        <div className="issue-meta">
          {issue.file}:{issue.line}{issue.column ? `:${issue.column}` : ''} · {issue.tool}/{issue.rule} · {issue.severity}
        </div>
      </div>
      <div className="issue-actions">
        <button className="btn small" onClick={() => onAsk(issue)}>Ask AI what is it</button>
        <button className="btn small primary" onClick={() => onHowToFix(issue)} disabled={fixDisabled}>
          How to Fix
        </button>
      </div>
    </div>
  )
}
