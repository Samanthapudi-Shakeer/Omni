import React, { useCallback, useEffect, useState } from 'react';
import { apiGet, apiPost, apiUpload } from './api';
import App from './App.jsx';
import StaticAnalysisPage from './components/StaticAnalysisPage.jsx';
import ModularizationPage from './components/ModularizationPage.jsx';
import TestGenPage from './components/TestGenPage.jsx';

const PAGES = [
  { id: 'aider', label: '◈ Aider Console' },
  { id: 'static-analysis', label: '🧹 Static Code Analysis' },
  { id: 'modularize', label: '🧩 Modularization' },
  { id: 'testgen', label: '🧪 Test Case Generation' },
];

const CURRENT_WS_KEY = 'aider_current_workspace';

export default function Shell() {
  const [page, setPage] = useState('aider');

  // Shared across all four pages: Static Code Analysis, Modularization, and
  // Test Case Generation always operate on whatever workspace is currently
  // selected in the Aider Console -- there's one workspace concept for the
  // whole app, not a separate picker per page.
  const [workspaces, setWorkspaces] = useState([]);
  const [currentWorkspace, setCurrentWorkspace] = useState('');

  const loadWorkspaces = useCallback(async () => {
    try {
      const { workspaces } = await apiGet('/api/workspaces');
      setWorkspaces(workspaces);
      return workspaces;
    } catch (_) {
      return [];
    }
  }, []);

  const createWorkspace = useCallback(async (name) => {
    const created = await apiPost('/api/workspaces', { name });
    await loadWorkspaces();
    setCurrentWorkspace(created.name);
  }, [loadWorkspaces]);

  useEffect(() => {
    (async () => {
      const list = await loadWorkspaces();
      // sessionStorage is per-tab: a fresh tab/window never auto-joins
      // whatever workspace happens to be first in the list.
      const saved = sessionStorage.getItem(CURRENT_WS_KEY);
      if (list.some((w) => w.name === saved)) {
        setCurrentWorkspace(saved);
      }
    })();
  }, [loadWorkspaces]);

  useEffect(() => {
    if (currentWorkspace) sessionStorage.setItem(CURRENT_WS_KEY, currentWorkspace);
  }, [currentWorkspace]);

  const uploadToWorkspace = async (files) => {
    if (!currentWorkspace || !files?.length) return;
    const form = new FormData(); [...files].forEach((file) => form.append('files', file));
    await apiUpload(`/api/ws/${encodeURIComponent(currentWorkspace)}/upload`, form);
    window.dispatchEvent(new Event('workspace-files-changed'));
  };

  const workspaceProps = {
    workspaces,
    currentWorkspace,
    onSelectWorkspace: setCurrentWorkspace,
    onCreateWorkspace: createWorkspace,
  };

  return (
    <div className="shell">
      <nav className="shell-navbar">
        {PAGES.map((p) => (
          <button
            key={p.id}
            className={page === p.id ? 'active' : ''}
            onClick={() => setPage(p.id)}
            type="button"
          >
            {p.label}
          </button>
        ))}
        <label className="workspace-folder-button" title="Add files or a folder to the selected workspace">📁 Workspace<input type="file" multiple hidden onChange={(e) => { uploadToWorkspace(e.target.files).catch(() => {}); e.target.value = ''; }} /></label>
      </nav>
      <div className="shell-body">
        {/* Keep every section mounted. Switching tabs must not cancel requests,
            discard tool progress, or create a fresh isolated Aider session. */}
        <div hidden={page !== 'aider'}><App {...workspaceProps} /></div>
        <div hidden={page !== 'static-analysis'}><StaticAnalysisPage {...workspaceProps} /></div>
        <div hidden={page !== 'modularize'}><ModularizationPage {...workspaceProps} /></div>
        <div hidden={page !== 'testgen'}><TestGenPage {...workspaceProps} /></div>
      </div>
    </div>
  );
}
