import React, { useEffect, useState } from 'react';
import { apiGet, apiPost } from '../api';
import { useWorkspaceFilesAndModels } from '../hooks/useWorkspaceFilesAndModels';
import ToolControls from './ToolControls';
import DiffView from './DiffView';
import Toasts from './Toasts';
import ToolTaskProgress from './ToolTaskProgress';

let toastId = 0;

const DEFAULT_PROMPT =
  'Generate comprehensive unit tests covering normal cases, edge cases, and error handling, ' +
  'using a testing framework appropriate for this language.';

export default function TestGenPage({ workspaces, currentWorkspace, onSelectWorkspace, onCreateWorkspace }) {
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
    const restore = async () => { try { const status = await apiGet(wsApi('/tasks/testgen/status')); if (alive && status.taskRunning) setRunning(true); } catch (_) { /* session has not been created yet */ } };
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
      // Runs on a dedicated, hidden Aider session for this workspace --
      // separate from the Aider Console -- and blocks until Aider actually
      // creates and commits the new test file.
      const res = await apiPost(wsApi('/tasks/testgen'), { path: selectedFile, paths: attachedPaths.length ? attachedPaths : [selectedFile], prompt: prompt.trim() });
      // The task endpoint only resolves after Aider reports completion. Still
      // wait for the generated paths to appear in the workspace listing
      // before telling the user it is ready, avoiding a transient "no file"
      // UI state on slower filesystems.
      const generated = (res.changedFiles || []).filter((f) => f.status !== 'D').map((f) => f.path);
      if (generated.length) {
        const deadline = Date.now() + 5000;
        while (Date.now() < deadline) {
          const listing = await apiGet(wsApi('/files/workspace'));
          if (generated.every((path) => listing.files.some((file) => file.path === path))) break;
          await new Promise((resolve) => setTimeout(resolve, 300));
        }
      }
      setResult(res);
      toast(
        res.changedFiles?.length ? 'Test file created and committed' : 'Aider did not create a new file',
        'success'
      );
      await tw.refreshWorkspaceFiles();
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
      await apiPost(wsApi('/tasks/testgen/undo'));
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
        <h1>🧪 Test Case Generation</h1>
        <p>
          Pick a file and describe what kind of tests you want. Aider attaches the file and creates a new test
          file directly — on its own dedicated hidden session, separate from the Aider Console.
        </p>
      </div>
      <label className="terminal-toggle"><input type="checkbox" checked={terminalEnabled} onChange={(e) => setTerminalEnabled(e.target.checked)} /> Show Aider terminal and answer Y/N prompts</label>
      <ToolTaskProgress running={running} statusPath={wsApi('/tasks/testgen/status')} terminalEnabled={terminalEnabled} />

      <ToolControls
        workspaces={workspaces} currentWorkspace={currentWorkspace}
        onSelectWorkspace={onSelectWorkspace} onCreateWorkspace={onCreateWorkspace}
        workspaceFiles={tw.workspaceFiles} selectedFile={selectedFile} onSelectFile={setSelectedFile} selectedFiles={attachedPaths} onSelectFiles={(paths) => { setAttachedPaths(paths); setSelectedFile(paths[0] || ''); }}
        showModel={false}
      />


      <div className="field multi-attach"><label>Attach related files or an entire folder</label><div className="tool-actions"><select value={folder} onChange={(e) => setFolder(e.target.value)}><option value="">Choose folder</option>{[...new Set(tw.workspaceFiles.map((f) => f.path.includes('/') ? f.path.split('/').slice(0, -1).join('/') : '').filter(Boolean))].map((item) => <option key={item} value={item}>{item}/</option>)}</select><button className="btn small" type="button" disabled={!folder} onClick={() => setAttachedPaths(tw.workspaceFiles.filter((f) => f.path.startsWith(`${folder}/`)).map((f) => f.path))}>Attach folder</button></div><div className="attachment-list">{tw.workspaceFiles.map((f) => <label key={f.path}><input type="checkbox" checked={attachedPaths.includes(f.path)} onChange={(e) => setAttachedPaths((old) => e.target.checked ? [...new Set([...old, f.path])] : old.filter((item) => item !== f.path))} /> {f.path}</label>)}</div></div>

      <div className="field">
        <label>What kind of tests do you want? (edit or use the default)</label>
        <textarea rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </div>

      <div className="tool-actions">
        <button className="btn primary" onClick={run} disabled={!selectedFile || !prompt.trim() || running}>
          {running ? '⏳ Aider is working…' : '▶ Generate tests'}
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
            <div className="empty">No new file was created.</div>
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
