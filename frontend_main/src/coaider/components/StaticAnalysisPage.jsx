import React, { useState } from 'react';
import { apiGet, apiPost } from '../api';
import { useWorkspaceFilesAndModels } from '../hooks/useWorkspaceFilesAndModels';
import ToolControls from './ToolControls';
import DiffView from './DiffView';
import SaveFileModal from './SaveFileModal';
import Toasts from './Toasts';

let toastId = 0;

export default function StaticAnalysisPage({ workspaces, currentWorkspace, onSelectWorkspace, onCreateWorkspace }) {
  const tw = useWorkspaceFilesAndModels(currentWorkspace);
  const [selectedModel, setSelectedModel] = useState('');
  const [engine, setEngine] = useState('semgrep');
  const [sonar, setSonar] = useState({ url: '', token: '', project: '' });
  const [target, setTarget] = useState('');
  const [filters, setFilters] = useState({ error: true, warning: true, refactor: true });
  const [analyzing, setAnalyzing] = useState(false);
  const [fixing, setFixing] = useState(false);
  const [findings, setFindings] = useState(null);
  const [fixResult, setFixResult] = useState(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [source, setSource] = useState(null);
  const [aiResult, setAiResult] = useState(null);
  const [aiBusy, setAiBusy] = useState(false);

  const wsApi = (path) => `/api/ws/${encodeURIComponent(currentWorkspace)}${path}`;
  const toast = (message, kind = 'info') => {
    const id = ++toastId;
    setToasts((t) => [...t, { id, message, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  };


  async function analyze() {
    if (!target) return;
    setAnalyzing(true);
    setFindings(null);
    setFixResult(null);
    try {
      const result = await apiPost(wsApi('/lint/analyze'), { path: target, engine, sonarUrl: sonar.url, sonarToken: sonar.token, sonarProject: sonar.project });
      setFindings(result.findings);
      toast(`Found ${result.findings.length} issue(s)`, result.findings.length ? 'info' : 'success');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setAnalyzing(false);
    }
  }

  async function autofix() {
    if (target.endsWith('/')) return;
    setFixing(true);
    try {
      const result = await apiPost(wsApi('/lint/autofix'), { path: target, model: selectedModel });
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

  async function showLocation(finding) {
    try { const data = await apiGet(wsApi(`/files/raw/${finding.path || target}`)); const line = Number(finding.line || 1); const rows = data.content.split('\n'); setSource({ path: finding.path || target, line, start: Math.max(1, line - 3), rows: rows.slice(Math.max(0, line - 4), line + 3) }); }
    catch (err) { toast(err.message, 'error'); }
  }
  async function askAi(finding) {
    setAiBusy(true); setAiResult(null);
    try { const data = await apiPost(wsApi('/lint/explain'), { path: finding.path || target, model: selectedModel, finding }); setAiResult({ kind: 'Explanation', ...data }); }
    catch (err) { toast(err.message, 'error'); } finally { setAiBusy(false); }
  }
  async function fixFinding(finding) {
    setAiBusy(true); setAiResult(null);
    try { const data = await apiPost(wsApi('/lint/fix-finding'), { path: finding.path || target, model: selectedModel, finding }); setAiResult({ kind: 'Proposed fix', ...data, path: finding.path || target }); }
    catch (err) { toast(err.message, 'error'); } finally { setAiBusy(false); }
  }
  function downloadPylintReport() { window.open(`${wsApi('/lint/pylint-report.pdf')}?path=${encodeURIComponent(target)}`, '_blank', 'noopener,noreferrer'); }

  const folders = [...new Set(tw.workspaceFiles
    .map((f) => f.path.split('/').slice(0, -1).join('/'))
    .filter(Boolean))];
  const visibleFindings = (findings || []).filter((finding) => {
    const kind = finding.type === 'fatal' ? 'error' : finding.type;
    return Boolean(filters[kind]);
  });

  return (
    <div className="tool-page">
      <div className="tool-page-header">
        <h1>🧹 Static Code Analysis</h1>
        <p>Runs Semgrep by default, or pylint, directly against one file or a folder. Only static-analysis findings are shown; formatting checks such as line length are not included. Review any proposed fix before applying it.</p>
      </div>

      <ToolControls
        workspaces={workspaces} currentWorkspace={currentWorkspace}
        onSelectWorkspace={onSelectWorkspace} onCreateWorkspace={onCreateWorkspace}
        workspaceFiles={tw.workspaceFiles} selectedFile={target} onSelectFile={setTarget}
        models={tw.models} selectedModel={selectedModel} onSelectModel={setSelectedModel}
      />

      <div className="tool-controls">
        <div className="field"><label>Analyzer</label><select value={engine} onChange={(e) => setEngine(e.target.value)}><option value="semgrep">Semgrep</option><option value="pylint">Pylint</option><option value="sonarqube">SonarQube</option></select></div>
        <div className="field"><label>Or analyze folder</label><select value={target} onChange={(e) => setTarget(e.target.value)}><option value="">Select a file or folder</option>{folders.map((folder) => <option key={folder} value={`${folder}/`}>{folder}/</option>)}</select></div>
      </div>

      {engine === 'sonarqube' && <div className="tool-controls"><div className="field"><label>SonarQube URL</label><input value={sonar.url} onChange={(e) => setSonar({ ...sonar, url: e.target.value })} placeholder="https://sonar.company.com" /></div><div className="field"><label>Token</label><input type="password" value={sonar.token} onChange={(e) => setSonar({ ...sonar, token: e.target.value })} /></div><div className="field"><label>Project key</label><input value={sonar.project} onChange={(e) => setSonar({ ...sonar, project: e.target.value })} /></div></div>}

      <div className="tool-actions">
        <label className="btn small upload-btn">Upload file(s)<input type="file" multiple hidden onChange={(e) => { handleUpload(e.target.files); e.target.value = ''; }} /></label>
        <label className="btn small upload-btn">Upload folder<input type="file" webkitdirectory="" directory="" multiple hidden onChange={(e) => { handleUpload(e.target.files); e.target.value = ''; }} /></label>
        <button className="btn primary" onClick={analyze} disabled={!target || analyzing}>
          {analyzing ? 'Analyzing…' : `▶ Run ${engine}`}
        </button>
      </div>

      <div className="tool-dashboard">
        {findings && (
          <div className="tool-card">
            <div className="tool-card-header">
              <span>Findings ({visibleFindings.length} of {findings.length})</span>
              <div className="finding-filters" aria-label="Filter findings">
                {['error', 'warning', 'refactor'].map((type) => <label key={type}><input type="checkbox" checked={filters[type]} onChange={(e) => setFilters((old) => ({ ...old, [type]: e.target.checked }))} /> {type}s</label>)}
              </div>
              {engine === 'pylint' && findings.length > 0 && <button className="btn small" onClick={downloadPylintReport}>↓ Pylint PDF report</button>}
              {findings.length > 0 && !target.endsWith('/') && (
                <button className="btn small primary" onClick={autofix} disabled={fixing || !selectedModel || engine !== 'pylint'} title={engine !== 'pylint' ? 'Auto-fix uses pylint findings' : ''}>
                  {fixing ? 'Fixing…' : '✨ Auto-fix with Ollama'}
                </button>
              )}
            </div>
            {visibleFindings.length === 0 ? (
              <div className="empty">No issues found.</div>
            ) : (
              <ul className="findings-list">
                {visibleFindings.map((f, i) => (
                  <li key={i} className={`finding-${f.type}`}>
                    <span className="finding-badge">{f.type}</span>
                    <button className="mono small finding-location" onClick={() => showLocation(f)} title="Open source at this location">{f.path && `${f.path} `}L{f.line}:{f.column}</button>
                    <span className="finding-symbol mono">{f.symbol}</span>
                    <span className="finding-msg">{f.message}</span>
                    <span className="finding-actions">
                      {(f.type === 'error' || f.type === 'fatal') && <button className="btn small" disabled={aiBusy || !selectedModel} onClick={() => askAi(f)}>Ask AI</button>}
                      {(f.type === 'error' || f.type === 'fatal' || f.type === 'refactor') && <button className="btn small" disabled={aiBusy || !selectedModel} onClick={() => fixFinding(f)}>Fix with AI</button>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {source && <div className="tool-card"><div className="tool-card-header"><span>{source.path} — lines {source.start}–{source.start + source.rows.length - 1}</span><button className="btn small" onClick={() => setSource(null)}>Close</button></div><pre className="source-preview">{source.rows.map((line, index) => `${String(source.start + index).padStart(5)} ${line}`).join('\n')}</pre></div>}
        {aiResult && <div className="tool-card"><div className="tool-card-header"><span>{aiResult.kind} ({aiResult.model || 'Aider'}){aiResult.committed ? ' — committed review copy' : ''}</span><button className="btn small" onClick={() => setAiResult(null)}>Close</button>{aiResult.changed && <button className="btn small primary" onClick={() => { setFixResult(aiResult); setSaveOpen(true); }}>Review / apply diff</button>}</div>{aiResult.explanation ? <p>{aiResult.explanation}</p> : aiResult.changed ? <DiffView diff={aiResult.diff} /> : <div className="empty">No change was proposed.</div>}</div>}

        {fixResult && (
          <div className="tool-card">
            <div className="tool-card-header">
              <span>Proposed fix ({fixResult.model})</span>
              {fixResult.changed && (
                <>
                  <button className="btn small primary" onClick={() => save(fixResult.path || target)}>✓ Apply to original</button>
                  <button className="btn small" onClick={() => setSaveOpen(true)}>Save as…</button>
                </>
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
        defaultPath={target}
        onCancel={() => setSaveOpen(false)}
        onConfirm={save}
      />
      <Toasts toasts={toasts} />
    </div>
  );
}
