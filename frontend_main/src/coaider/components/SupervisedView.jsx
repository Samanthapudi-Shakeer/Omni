import React, { useEffect, useRef, useState } from 'react';
import QuestionPrompt from './QuestionPrompt';
import DiffView from './DiffView';

const FILE_ICON = { pending: '○', editing: '◐', done: '✓' };

function fmtElapsed(sec) {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m ${s}s`;
}

export default function SupervisedView({
  workspaceFiles,
  taskRunning,
  transcript,
  phaseTimeline,
  fileProgress,
  elapsedSeconds,
  pendingQuestion,
  lastResult,
  prefillText,
  prefillNonce,
  onStartTask,
  onStopTask,
  onAnswer,
  onSwitchToTerminal,
  onOpenDiffViewer,
  onOpenCodeCanvas,
  onFollowUp,
}) {
  const [text, setText] = useState('');
  const [selected, setSelected] = useState(new Set());
  const transcriptRef = useRef(null);

  useEffect(() => {
    if (prefillNonce) setText(prefillText || '');
  }, [prefillNonce, prefillText]);

  useEffect(() => {
    if (transcriptRef.current) transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
  }, [transcript]);

  function toggleFile(path) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  function submit(e) {
    e.preventDefault();
    if (!text.trim() || taskRunning) return;
    onStartTask(text.trim(), Array.from(selected));
    setText('');
  }

  const fileEntries = Object.entries(fileProgress || {});
  const changedPaths = lastResult ? lastResult.changedFiles.map((f) => f.path) : [];

  return (
    <div className="supervised">
      <div className="supervised-header">
        <div>
          <div className="supervised-title">Supervised Mode</div>
          <div className="supervised-sub">Aider runs hidden — you only see progress and questions.</div>
        </div>
        <button className="btn small" type="button" onClick={onSwitchToTerminal}>Switch to Terminal Mode</button>
      </div>

      {!taskRunning && !pendingQuestion && (
        <form className="supervised-form supervised-card" onSubmit={submit}>
          <div className="supervised-form-head">
            <label>Files for this task</label>
            {selected.size > 0 && <span className="context-pill">{selected.size} selected</span>}
          </div>
          <div className="supervised-file-picker">
            {workspaceFiles.length === 0 && <div className="empty">No files in workspace yet.</div>}
            {workspaceFiles.map((f) => (
              <label key={f.path} className={`file-checkbox${selected.has(f.path) ? ' checked' : ''}`}>
                <input type="checkbox" checked={selected.has(f.path)} onChange={() => toggleFile(f.path)} />
                <span className="mono">{f.path}</span>
              </label>
            ))}
          </div>
          <label>Task</label>
          <textarea
            rows={4}
            placeholder="Describe what you want Aider to do…"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button className="btn primary" type="submit" disabled={!text.trim()}>▶ Start Task</button>
        </form>
      )}

      {(transcript.length > 0 || (taskRunning && !pendingQuestion)) && (
        <div className="transcript-panel" ref={transcriptRef}>
          {transcript.length === 0 && (
            <div className="phase-indicator">
              <span className="spinner" />
              Processing input…
            </div>
          )}
          {transcript.map((entry, i) => (
            <div key={i} className="transcript-bubble">{entry}</div>
          ))}
        </div>
      )}

      {(taskRunning || pendingQuestion) && (
        <div className="supervised-progress">
          <div className="supervised-progress-topline">
            <span className="elapsed-badge">⏱ {fmtElapsed(elapsedSeconds)}</span>
            {fileEntries.length > 0 && (
              <div className="file-checklist">
                {fileEntries.map(([path, state]) => (
                  <span key={path} className={`file-checklist-item fc-${state}`} title={path}>
                    <span className="fc-icon">{FILE_ICON[state] || '○'}</span>
                    <span className="mono">{path}</span>
                  </span>
                ))}
              </div>
            )}
          </div>

          {pendingQuestion && <QuestionPrompt question={pendingQuestion} onAnswer={onAnswer} />}

          {phaseTimeline.length > 0 && (
            <div className="phase-timeline">
              {phaseTimeline.map((p, i) => (
                <div key={i} className={`phase-timeline-item${i === phaseTimeline.length - 1 ? ' current' : ''}`}>
                  <span className="phase-dot" />{p.label}
                </div>
              ))}
            </div>
          )}

          <button className="btn" type="button" onClick={onStopTask}>■ Stop Task</button>
        </div>
      )}

      {!taskRunning && !pendingQuestion && lastResult && (
        <div className="task-result supervised-card">
          <div className="task-result-header">
            <span>Last task result</span>
            <div className="task-result-actions">
              {changedPaths.length > 0 && (
                <button className="btn small" type="button" onClick={() => onOpenCodeCanvas(changedPaths[0], changedPaths)}>
                  ◪ Code Canvas
                </button>
              )}
              {lastResult.diff && (
                <button className="btn small" type="button" onClick={() => onOpenDiffViewer(lastResult)}>
                  Open in Diff Viewer ↗
                </button>
              )}
            </div>
          </div>
          {lastResult.changedFiles.length === 0 ? (
            <div className="empty">No files were changed.</div>
          ) : (
            <>
              <div className="task-result-files">
                {lastResult.changedFiles.map((f) => (
                  <div key={f.path} className="task-result-file">
                    <span className={`change-badge change-${f.status}`}>{f.status}</span>
                    <span className="mono">{f.path}</span>
                    <button className="mini" onClick={() => onOpenCodeCanvas(f.path, changedPaths)}>Versions</button>
                  </div>
                ))}
              </div>
              {lastResult.commits.length > 0 && (
                <div className="task-result-commits mono small dim">{lastResult.commits.join('\n')}</div>
              )}
              {lastResult.diff && <DiffView diff={lastResult.diff} />}
            </>
          )}
          <div className="task-result-followup">
            <button className="btn small" type="button" onClick={onFollowUp}>
              ↺ Follow up on this
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
