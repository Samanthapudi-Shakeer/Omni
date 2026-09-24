import React, { useState } from 'react';
import { apiPost } from '../api';
import { useWorkspaceFilesAndModels } from '../hooks/useWorkspaceFilesAndModels';
import ToolControls from './ToolControls';
import DiffView from './DiffView';
import Toasts from './Toasts';

let toastId = 0;

const DEFAULT_PROMPT =
  'Generate comprehensive unit tests covering normal cases, edge cases, and error handling, ' +
  'using a testing framework appropriate for this language.';

export default function TestGenPage({ workspaces, currentWorkspace, onSelectWorkspace, onCreateWorkspace }) {
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

  async function run() {
    if (!selectedFile || !prompt.trim()) return;
    setRunning(true);
    setResult(null);
    try {
      // Runs on a dedicated, hidden Aider session for this workspace --
      // separate from the Aider Console -- and blocks until Aider actually
      // creates and commits the new test file.
      const res = await apiPost(wsApi('/tasks/testgen'), { path: selectedFile, prompt: prompt.trim() });
      setResult(res);
      toast(
        res.changedFiles?.length ? 'Test file created and committed' : 'Aider did not create a new file',
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

      <ToolControls
        workspaces={workspaces} currentWorkspace={currentWorkspace}
        onSelectWorkspace={onSelectWorkspace} onCreateWorkspace={onCreateWorkspace}
        workspaceFiles={tw.workspaceFiles} selectedFile={selectedFile} onSelectFile={setSelectedFile}
        showModel={false}
      />

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
