import React, { useState } from 'react';

const STATUS_META = {
  stopped: { label: 'Stopped', cls: 'st-stopped' },
  starting: { label: 'Starting…', cls: 'st-busy' },
  running: { label: 'Processing…', cls: 'st-busy' },
  waiting_input: { label: 'Waiting for input', cls: 'st-waiting' },
  idle: { label: 'Idle', cls: 'st-idle' },
  error: { label: 'Error', cls: 'st-error' },
  crashed: { label: 'Crashed', cls: 'st-error' },
};

export default function StatusBar({
  status,
  model,
  tokens,
  ollamaConnected,
  ollamaError,
  workspace,
  onRefreshTokens,
  onOpenLibrary,
}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState('status'); // 'status' | 'tokens'
  const meta = STATUS_META[status] || { label: status, cls: '' };

  return (
    <div className="status-bar">
      <span className={`status-chip ${meta.cls}`}>
        <span className="status-chip-dot" />
        {meta.label}
      </span>
      <span className="status-model mono">{model || '—'}</span>
      <button className="icon-btn" type="button" title="Command library (Ctrl/Cmd+K)" onClick={onOpenLibrary}>
        📚
      </button>
      <button
        className="info-btn"
        type="button"
        title="Connection & token status"
        onClick={() => setOpen((v) => !v)}
      >
        i
      </button>

      {open && (
        <div className="status-popover">
          <div className="status-popover-header">
            <div className="status-popover-tabs">
              <button className={tab === 'status' ? 'active' : ''} onClick={() => setTab('status')} type="button">
                Connection
              </button>
              <button
                className={tab === 'tokens' ? 'active' : ''}
                onClick={() => { setTab('tokens'); onRefreshTokens?.(); }}
                type="button"
              >
                Tokens
              </button>
            </div>
            <button className="mini" onClick={() => setOpen(false)}>✕</button>
          </div>

          {tab === 'status' ? (
            <div className="status-popover-body">
              <div className="conn-row">
                <span className={`conn-dot ${meta.cls}`} />
                <div>
                  <div className="conn-label">Aider</div>
                  <div className="conn-value">{meta.label}</div>
                </div>
              </div>
              <div className="conn-row">
                <span className={`conn-dot ${ollamaConnected ? 'st-idle' : 'st-error'}`} />
                <div>
                  <div className="conn-label">Ollama</div>
                  <div className="conn-value">{ollamaConnected ? 'Connected' : (ollamaError || 'Unavailable')}</div>
                </div>
              </div>
              {workspace && (
                <div className="conn-workspace mono dim small" title={workspace}>{workspace}</div>
              )}
            </div>
          ) : tokens ? (
            <div className="status-popover-body">
              <div className="token-bar">
                <div
                  className="token-bar-fill"
                  style={{
                    width: `${Math.min(
                      100,
                      tokens.used && tokens.remaining
                        ? (tokens.used / (tokens.used + tokens.remaining)) * 100
                        : 0
                    )}%`,
                  }}
                />
              </div>
              <div className="token-stats">
                <div><strong>{tokens.used?.toLocaleString() ?? '—'}</strong> used</div>
                <div><strong>{tokens.remaining?.toLocaleString() ?? '—'}</strong> remaining</div>
              </div>
              {tokens.breakdown && tokens.breakdown.length > 0 && (
                <ul className="token-breakdown">
                  {tokens.breakdown.map((b, i) => (
                    <li key={i}><span>{b.label}</span><span className="mono">{b.tokens}</span></li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <div className="status-popover-body">
              <div className="token-empty">No token report yet — fetching…</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
