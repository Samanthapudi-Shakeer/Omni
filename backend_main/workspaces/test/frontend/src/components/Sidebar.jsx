import React, { useRef } from 'react';

function fmtSize(n) {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${(n / 1024 / 1024).toFixed(1)}MB`;
}

function fmtTokens(n) {
  if (n < 1000) return `${n}`;
  return `${(n / 1000).toFixed(1)}k`;
}

function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

const STATUS_BADGE = { A: 'added', M: 'modified', D: 'deleted' };

export default function Sidebar({
  workspaceBar,
  aider,
  ollamaConnected,
  models,
  workspaceFiles,
  attachedFiles,
  context,
  modifiedFiles,
  history,
  onDownloadFile,
  onUndo,
  onStart,
  onStop,
  onRestart,
  onClear,
  onTokens,
  onModeChange,
  onModelChange,
  onAddFile,
  onDropFile,
  onRefreshFiles,
  onUpload,
}) {
  const fileInputRef = useRef(null);
  const attachedSet = new Set(attachedFiles);

  return (
    <aside className="rail">
      <div className="rail-brand">
        <span className="brand-mark">◈</span>
        <div>
          <div className="brand-title">Aider Console</div>
          <div className="brand-sub">remote control panel</div>
        </div>
      </div>

      {workspaceBar}

      <div className="rail-card">
        <div className="field">
          <label htmlFor="sel-model">Model (Ollama)</label>
          <select id="sel-model" value={aider.model} onChange={(e) => onModelChange(e.target.value)}>
            {models.length === 0 && <option>{ollamaConnected ? 'No models found' : 'Ollama unavailable'}</option>}
            {models.map((m) => (
              <option key={m} value={`ollama/${m}`}>{m}</option>
            ))}
          </select>
        </div>

        <div className="field">
          <label>Mode</label>
          <div className="segmented">
            {['ask', 'code', 'architect'].map((m) => (
              <button
                key={m}
                className={aider.mode === m ? 'active' : ''}
                onClick={() => onModeChange(m)}
                type="button"
              >
                {m[0].toUpperCase() + m.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="rail-card">
        <div className="field row-buttons">
          <button
            className="btn primary"
            disabled={!['stopped', 'crashed', 'error'].includes(aider.status)}
            onClick={onStart}
            title="Start the Aider process for this workspace"
          >
            ▶ Start
          </button>
          <button className="btn" disabled={aider.status === 'stopped'} onClick={onStop} title="Stop the Aider process">■ Stop</button>
          <button className="btn" onClick={onRestart} title="Stop and immediately start Aider again">↻ Restart</button>
        </div>
      </div>

      <div className="rail-card commands-card">
        <label>Quick commands</label>
        <div className="field row-buttons commands-row">
          <button
            className="btn ghost small"
            onClick={onClear}
            title="Clear the chat history (keeps attached files)."
          >
            /clear
          </button>
          <button
            className="btn ghost small"
            onClick={onTokens}
            title="Show token usage: how much of the model's context window is used vs remaining."
          >
            /tokens
          </button>
        </div>
      </div>

      <div className="field grow rail-card">
        <div className="file-section-head">
          <label>Workspace files</label>
          <div className="file-toolbar">
            <button className="btn small" onClick={onRefreshFiles} type="button">Refresh</button>
            <label className="btn small upload-btn">
              Upload
              <input
                ref={fileInputRef}
                type="file"
                multiple
                hidden
                onChange={(e) => {
                  onUpload(e.target.files);
                  e.target.value = '';
                }}
              />
            </label>
          </div>
        </div>
        <ul className="file-list">
          {workspaceFiles.length === 0 && <li className="empty">No files yet — upload something.</li>}
          {workspaceFiles.map((f) => {
            const isAttached = attachedSet.has(f.path);
            return (
              <li key={f.path} className={isAttached ? 'attached' : ''}>
                <span className="fdot" data-on={isAttached ? '1' : '0'} />
                <span className="fname" title={f.path}>{f.path}</span>
                <span className="fsize">{fmtSize(f.size)}</span>
                {isAttached ? (
                  <button className="mini mini-drop" onClick={() => onDropFile(f.path)}>Drop</button>
                ) : (
                  <button className="mini" onClick={() => onAddFile(f.path)}>Add</button>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      <div className="field grow rail-card">
        <div className="file-section-head">
          <label>Attached to Aider</label>
          <span className="context-pill" title="Attached files / estimated tokens in context">
            {context.fileCount} file{context.fileCount === 1 ? '' : 's'} · ~{fmtTokens(context.estTokens)} tok
          </span>
        </div>
        <ul className="file-list">
          {attachedFiles.length === 0 && <li className="empty">Nothing attached yet.</li>}
          {attachedFiles.map((f) => (
            <li key={f} className="attached">
              <span className="fdot" data-on="1" />
              <span className="fname" title={f}>{f}</span>
              <button className="mini mini-drop" onClick={() => onDropFile(f)}>Drop</button>
            </li>
          ))}
        </ul>
      </div>

      {modifiedFiles.length > 0 && (
        <div className="field grow rail-card">
          <div className="file-section-head">
            <label>Modified this session</label>
            <span className="context-pill">{modifiedFiles.length} file{modifiedFiles.length === 1 ? '' : 's'}</span>
          </div>
          <ul className="file-list modified-list">
            {modifiedFiles.map((f) => (
              <li key={f.path}>
                <span className={`change-dot change-${f.status}`} title={STATUS_BADGE[f.status] || f.status} />
                <span className="fname" title={f.path}>{f.path}</span>
                <span className="fsize">{fmtTime(f.changedAt)}</span>
                <button className="mini mini-download" onClick={() => onDownloadFile(f.path)} title="Download this file">⭳</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {history.length > 0 && (
        <div className="field grow rail-card">
          <div className="file-section-head">
            <label>Version history (this session)</label>
            <button className="btn small" type="button" onClick={onUndo} title="Undo Aider's most recent change">
              ↶ Undo latest
            </button>
          </div>
          <ul className="history-list">
            {history.map((h, i) => (
              <li key={h.hash}>
                <span className="history-index">{history.length - 1 - i}</span>
                <div className="history-body">
                  <div className="history-subject" title={h.subject}>{h.subject}</div>
                  <div className="history-meta mono dim small">
                    {h.shortHash} · {fmtTime(h.timestamp)} · {h.files.length} file{h.files.length === 1 ? '' : 's'}
                  </div>
                </div>
              </li>
            ))}
            <li className="history-origin">
              <span className="history-index">0</span>
              <div className="history-body">
                <div className="history-subject dim">Session start</div>
              </div>
            </li>
          </ul>
        </div>
      )}
    </aside>
  );
}
