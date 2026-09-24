import { useState } from 'react'
import { applyFix, extractErrorMessage } from '../api/client'

export default function HowToFixModal({ workspace, issue, result, loading, error, onClose, onApplied }) {
  const [applying, setApplying] = useState(false)
  const [applyResult, setApplyResult] = useState(null)
  const [applyError, setApplyError] = useState(null)

  if (!issue) return null

  const handleApply = async () => {
    if (!result) return
    setApplying(true)
    setApplyError(null)
    try {
      const res = await applyFix(workspace, issue, result.start_line, result.end_line, result.fixed_code)
      setApplyResult(res)
      if (res.status === 'ok') {
        onApplied?.(issue, res)
      }
    } catch (e) {
      setApplyError(extractErrorMessage(e))
    } finally {
      setApplying(false)
    }
  }

  const alreadyApplied = applyResult?.status === 'ok'
  const canApply = !!result?.fixed_code?.trim() && !alreadyApplied

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width: 760 }} onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <h4>How to Fix — {issue.tool} / {issue.rule}</h4>
        <div className="issue-meta" style={{ marginBottom: 12 }}>
          {issue.file}:{issue.line} · {issue.severity}
        </div>

        {loading && (
          <div className="empty-state">
            <span className="spinner" /> Sending the whole file to Ollama for context…
          </div>
        )}

        {!loading && error && (
          <div className="hint" style={{ color: 'var(--err)' }}>{error}</div>
        )}

        {!loading && !error && result && (
          <>
            <p style={{ fontSize: 13.5, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{result.explanation}</p>

            {result.diff ? (
              <>
                <div className="section-label">SUGGESTED CHANGE (lines {result.start_line}-{result.end_line})</div>
                <div className="diff-box">{result.diff}</div>
              </>
            ) : (
              <div className="hint">The model didn't return a concrete code change to preview - see the explanation above.</div>
            )}

            <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 10 }}>
              <button className="btn primary" onClick={handleApply} disabled={!canApply || applying}>
                {applying ? <><span className="spinner" /> Applying…</> : alreadyApplied ? 'Applied ✓' : 'Apply this fix'}
              </button>
              {!canApply && !alreadyApplied && (
                <span className="hint" style={{ margin: 0 }}>Nothing to apply for this suggestion.</span>
              )}
            </div>

            {alreadyApplied && (
              <div className="hint" style={{ color: '#1e9e5c', marginTop: 8 }}>
                Written to {issue.file} and committed to its version history
                {applyResult.commit ? ` (${applyResult.commit.slice(0, 7)})` : ''}.
              </div>
            )}
            {applyError && (
              <div className="hint" style={{ color: 'var(--err)', marginTop: 8 }}>{applyError}</div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
