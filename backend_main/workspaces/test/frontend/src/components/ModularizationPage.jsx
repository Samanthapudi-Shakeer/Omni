import React, { useState } from 'react';
import { apiPost, apiUpload } from '../api';
import { useWorkspaceFilesAndModels } from '../hooks/useWorkspaceFilesAndModels';
import ToolControls from './ToolControls';
import DiffView from './DiffView';
import Toasts from './Toasts';

let toastId = 0;

const DEFAULT_PROMPT =
  'Refactor this file into smaller, well-organized functions/modules without changing its behavior. ' +
  'Split logically related code into clearly separated sections, improve naming, and add brief docstrings.';

export default function ModularizationPage({ workspaces, currentWorkspace, onSelectWorkspace, onCreateWorkspace }) {
  const tw = useWorkspaceFilesAndModels(currentWorkspace);
  const [selectedFile, setSelectedFile] = useState('');
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [toasts, setToasts] = useState([]);

  const wsApi = (path) => `/api/ws/${encodeURIComponent(currentWorkspace)}${path}`;
  const toast = (message, kind = 'info') => {
    const id = ++toastId;
    setToasts((t) => [...t, { id, message, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  };

  async function handleUpload(fileList) {
    if (!fileList || fileList.length === 0 || !currentWorkspace) return;
    try {
      const form = new FormData();
      for (const f of fileList) form.append('files', f);
      const body = await apiUpload(wsApi('/upload'), form);
      toast(`Uploaded ${body.uploaded.length} file(s)`, 'success');
      await tw.refreshWorkspaceFiles();
      if (body.uploaded[0]) setSelectedFile(body.uploaded[0].name);
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  async function run() {
    if (!selectedFile || !prompt.trim()) return;
    setRunning(true);
    setResult(null);
    try {
      // This runs on a dedicated, hidden Aider session for this workspace --
      // separate from whatever's happening in the Aider Console -- and
      // blocks until Aider actually finishes and commits the change.
      const res = await apiPost(wsApi('/tasks/modularize'), { path: selectedFile, prompt: prompt.trim() });
      setResult(res);
      toast(
        res.changedFiles?.length ? 'Modularization complete — changes applied and committed' : 'Aider made no changes',
        'success'
      );
      tw.refreshWorkspaceFiles();
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setRunning(false);
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

      <ToolControls
        workspaces={workspaces} currentWorkspace={currentWorkspace}
        onSelectWorkspace={onSelectWorkspace} onCreateWorkspace={onCreateWorkspace}
        workspaceFiles={tw.workspaceFiles} selectedFile={selectedFile} onSelectFile={setSelectedFile}
        showModel={false}
      />

      <div className="field">
        <label>Or upload a new file</label>
        <label className="btn small upload-btn" style={{ width: 'fit-content' }}>
          Upload file(s)
          <input type="file" multiple hidden onChange={(e) => { handleUpload(e.target.files); e.target.value = ''; }} />
        </label>
      </div>

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
