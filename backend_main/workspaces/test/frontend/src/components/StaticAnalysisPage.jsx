import React, { useState } from 'react';
import { apiPost } from '../api';
import { useWorkspaceFilesAndModels } from '../hooks/useWorkspaceFilesAndModels';
import ToolControls from './ToolControls';
import DiffView from './DiffView';
import SaveFileModal from './SaveFileModal';
import Toasts from './Toasts';

let toastId = 0;

export default function StaticAnalysisPage({ workspaces, currentWorkspace, onSelectWorkspace, onCreateWorkspace }) {
  const tw = useWorkspaceFilesAndModels(currentWorkspace);
  const [selectedFile, setSelectedFile] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [fixing, setFixing] = useState(false);
  const [findings, setFindings] = useState(null);
  const [fixResult, setFixResult] = useState(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [toasts, setToasts] = useState([]);

  const wsApi = (path) => `/api/ws/${encodeURIComponent(currentWorkspace)}${path}`;
  const toast = (message, kind = 'info') => {
    const id = ++toastId;
    setToasts((t) => [...t, { id, message, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  };

  async function analyze() {
    if (!selectedFile) return;
    setAnalyzing(true);
    setFindings(null);
    setFixResult(null);
    try {
      const result = await apiPost(wsApi('/lint/analyze'), { path: selectedFile });
      setFindings(result.findings);
      toast(`Found ${result.findings.length} issue(s)`, result.findings.length ? 'info' : 'success');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setAnalyzing(false);
    }
  }

  async function autofix() {
    setFixing(true);
    try {
      const result = await apiPost(wsApi('/lint/autofix'), { path: selectedFile, model: selectedModel });
      setFixResult(result);
      toast(result.changed ? 'Fix generated — review the diff below' : 'Model made no changes', 'success');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setFixing(false);
    }
  }

  async function save(path) {
    try {
      await apiPost(wsApi('/files/write'), { path, content: fixResult.result });
      toast(`Saved ${path}`, 'success');
      setSaveOpen(false);
      tw.refreshWorkspaceFiles();
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  return (
    <div className="tool-page">
      <div className="tool-page-header">
        <h1>🧹 Static Code Analysis</h1>
        <p>Runs pylint directly (no LLM involved), then — if you want — asks the selected Ollama model to fix what it found. Review the diff before anything is saved.</p>
      </div>

      <ToolControls
        workspaces={workspaces} currentWorkspace={currentWorkspace}
        onSelectWorkspace={onSelectWorkspace} onCreateWorkspace={onCreateWorkspace}
        workspaceFiles={tw.workspaceFiles} selectedFile={selectedFile} onSelectFile={setSelectedFile}
        models={tw.models} selectedModel={selectedModel} onSelectModel={setSelectedModel}
      />

      <div className="tool-actions">
        <button className="btn primary" onClick={analyze} disabled={!selectedFile || analyzing}>
          {analyzing ? 'Analyzing…' : '▶ Run pylint'}
        </button>
      </div>

      <div className="tool-dashboard">
        {findings && (
          <div className="tool-card">
            <div className="tool-card-header">
              <span>Findings ({findings.length})</span>
              {findings.length > 0 && (
                <button className="btn small primary" onClick={autofix} disabled={fixing || !selectedModel}>
                  {fixing ? 'Fixing…' : '✨ Auto-fix with Ollama'}
                </button>
              )}
            </div>
            {findings.length === 0 ? (
              <div className="empty">No issues found.</div>
            ) : (
              <ul className="findings-list">
                {findings.map((f, i) => (
                  <li key={i} className={`finding-${f.type}`}>
                    <span className="finding-badge">{f.type}</span>
                    <span className="mono small">L{f.line}:{f.column}</span>
                    <span className="finding-symbol mono">{f.symbol}</span>
                    <span className="finding-msg">{f.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {fixResult && (
          <div className="tool-card">
            <div className="tool-card-header">
              <span>Proposed fix ({fixResult.model})</span>
              {fixResult.changed && (
                <button className="btn small" onClick={() => setSaveOpen(true)}>💾 Save…</button>
              )}
            </div>
            {!fixResult.changed ? (
              <div className="empty">The model didn't propose any changes.</div>
            ) : (
              <DiffView diff={fixResult.diff} />
            )}
          </div>
        )}
      </div>

      <SaveFileModal
        open={saveOpen}
        defaultPath={selectedFile}
        onCancel={() => setSaveOpen(false)}
        onConfirm={save}
      />
      <Toasts toasts={toasts} />
    </div>
  );
}
