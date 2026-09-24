import React, { useEffect, useState } from 'react';
import { apiGet, apiPost } from '../api';
import { useWorkspaceFilesAndModels } from '../hooks/useWorkspaceFilesAndModels';
import ToolControls from './ToolControls';
import DiffView from './DiffView';
import Toasts from './Toasts';
import ToolTaskProgress from './ToolTaskProgress';

let toastId = 0;

const DEFAULT_PROMPT =
  'Refactor this file into smaller, well-organized functions/modules without changing its behavior. ' +
  'Split logically related code into clearly separated sections, improve naming, and add brief docstrings.';

export default function ModularizationPage({ workspaces, currentWorkspace, onSelectWorkspace, onCreateWorkspace }) {
  const tw = useWorkspaceFilesAndModels(currentWorkspace);
  const [selectedFile, setSelectedFile] = useState('');
  const [attachedPaths, setAttachedPaths] = useState([]);
  const [folder, setFolder] = useState('');
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [terminalEnabled, setTerminalEnabled] = useState(true);

  const wsApi = (path) => `/api/ws/${encodeURIComponent(currentWorkspace)}${path}`;
  useEffect(() => {
    if (!currentWorkspace) return;
    let alive = true;
    const restore = async () => { try { const status = await apiGet(wsApi('/tasks/modularize/status')); if (alive && status.taskRunning) setRunning(true); } catch (_) { /* session has not been created yet */ } };
    restore();
    return () => { alive = false; };
  }, [currentWorkspace]);
  const toast = (message, kind = 'info') => {
    const id = ++toastId;
    setToasts((t) => [...t, { id, message, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  };


  async function run() {
    if (!selectedFile || !prompt.trim()) return;
    setRunning(true);
    setResult(null);
    let keepRunning = false;
    try {
      // This runs on a dedicated, hidden Aider session for this workspace --
      // separate from whatever's happening in the Aider Console -- and
      // blocks until Aider actually finishes and commits the change.
      const res = await apiPost(wsApi('/tasks/modularize'), { path: selectedFile, paths: attachedPaths.length ? attachedPaths : [selectedFile], prompt: prompt.trim() });
      setResult(res);
      toast(
        res.changedFiles?.length ? 'Modularization complete — changes applied and committed' : 'Aider made no changes',
        'success'
      );
      tw.refreshWorkspaceFiles();
    } catch (err) {
      keepRunning = /already running/i.test(err.message);
      if (keepRunning) toast('This Aider task is already running. Reconnected to its terminal.', 'info');
      else toast(err.message, 'error');
    } finally {
      if (!keepRunning) setRunning(false);
    }
  }

  async function undo() {
    try {
      await apiPost(wsApi('/tasks/modularize/undo'));
      toast('Undid the last change', 'success');
      setResult(null);
      tw.refreshWorkspaceFiles();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  return (
    <div className="tool-page">
      <div className="tool-page-header">
        <h1>🧩 Modularization</h1>
        <p>
          Upload a file (or pick one already in the workspace), describe how you want it restructured, and Aider
          will make the change directly — on its own dedicated hidden session, separate from the Aider Console, so
          it never interrupts anything you have running there.
        </p>
      </div>
      <label className="terminal-toggle"><input type="checkbox" checked={terminalEnabled} onChange={(e) => setTerminalEnabled(e.target.checked)} /> Show Aider terminal and answer Y/N prompts</label>
      <ToolTaskProgress running={running} statusPath={wsApi('/tasks/modularize/status')} terminalEnabled={terminalEnabled} />

      <ToolControls
        workspaces={workspaces} currentWorkspace={currentWorkspace}
        onSelectWorkspace={onSelectWorkspace} onCreateWorkspace={onCreateWorkspace}
        workspaceFiles={tw.workspaceFiles} selectedFile={selectedFile} onSelectFile={setSelectedFile} selectedFiles={attachedPaths} onSelectFiles={(paths) => { setAttachedPaths(paths); setSelectedFile(paths[0] || ''); }}
        showModel={false}
      />


      <div className="field multi-attach"><label>Attach related files or an entire folder</label><div className="tool-actions"><select value={folder} onChange={(e) => setFolder(e.target.value)}><option value="">Choose folder</option>{[...new Set(tw.workspaceFiles.map((f) => f.path.includes('/') ? f.path.split('/').slice(0, -1).join('/') : '').filter(Boolean))].map((item) => <option key={item} value={item}>{item}/</option>)}</select><button className="btn small" type="button" disabled={!folder} onClick={() => setAttachedPaths(tw.workspaceFiles.filter((f) => f.path.startsWith(`${folder}/`)).map((f) => f.path))}>Attach folder</button></div><div className="attachment-list">{tw.workspaceFiles.map((f) => <label key={f.path}><input type="checkbox" checked={attachedPaths.includes(f.path)} onChange={(e) => setAttachedPaths((old) => e.target.checked ? [...new Set([...old, f.path])] : old.filter((item) => item !== f.path))} /> {f.path}</label>)}</div></div>

      <div className="field multi-attach"><label>Attach related files or an entire folder</label><div className="tool-actions"><select value={folder} onChange={(e) => setFolder(e.target.value)}><option value="">Choose folder</option>{[...new Set(tw.workspaceFiles.map((f) => f.path.includes('/') ? f.path.split('/').slice(0, -1).join('/') : '').filter(Boolean))].map((item) => <option key={item} value={item}>{item}/</option>)}</select><button className="btn small" type="button" disabled={!folder} onClick={() => setAttachedPaths(tw.workspaceFiles.filter((f) => f.path.startsWith(`${folder}/`)).map((f) => f.path))}>Attach folder</button></div><div className="attachment-list">{tw.workspaceFiles.map((f) => <label key={f.path}><input type="checkbox" checked={attachedPaths.includes(f.path)} onChange={(e) => setAttachedPaths((old) => e.target.checked ? [...new Set([...old, f.path])] : old.filter((item) => item !== f.path))} /> {f.path}</label>)}</div></div>

      <div className="field">
        <label>Prompt (edit or use the default)</label>
        <textarea rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </div>

      <div className="tool-actions">
        <button className="btn primary" onClick={run} disabled={!selectedFile || !prompt.trim() || running}>
          {running ? '⏳ Aider is working…' : '▶ Modularize'}
        </button>
      </div>

      {result && (
      <div className="tool-dashboard">
        <div className="tool-card">
          <div className="tool-card-header">
            <span>Result</span>
            {result.changedFiles?.length > 0 && (
              <button className="btn small" onClick={undo}>↶ Undo last change</button>
            )}
          </div>
          {!result.changedFiles?.length ? (
            <div className="empty">No files were changed.</div>
          ) : (
            <>
              <div className="task-result-files">
                {result.changedFiles.map((f) => (
                  <div key={f.path} className="task-result-file">
                    <span className={`change-badge change-${f.status}`}>{f.status}</span>
                    <span className="mono">{f.path}</span>
                  </div>
                ))}
              </div>
              {result.commits?.length > 0 && (
                <div className="task-result-commits mono small dim">{result.commits.join('\n')}</div>
              )}
              {result.diff && <DiffView diff={result.diff} />}
            </>
          )}
        </div>
      </div>
      )}

      <Toasts toasts={toasts} />
    </div>
  );
}
