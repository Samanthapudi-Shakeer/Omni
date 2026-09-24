import { useCallback, useEffect, useState } from 'react';
import { apiGet, apiPost } from '../api';

export function useToolWorkspace() {
  const [workspaces, setWorkspaces] = useState([]);
  const [currentWorkspace, setCurrentWorkspace] = useState('');
  const [workspaceFiles, setWorkspaceFiles] = useState([]);
  const [models, setModels] = useState([]);

  const loadWorkspaces = useCallback(async () => {
    const { workspaces } = await apiGet('/api/workspaces');
    setWorkspaces(workspaces);
    return workspaces;
  }, []);

  const createWorkspace = useCallback(async (name) => {
    const created = await apiPost('/api/workspaces', { name });
    await loadWorkspaces();
    setCurrentWorkspace(created.name);
  }, [loadWorkspaces]);

  const refreshWorkspaceFiles = useCallback(async () => {
    if (!currentWorkspace) { setWorkspaceFiles([]); return; }
    const { files } = await apiGet(`/api/ws/${encodeURIComponent(currentWorkspace)}/files/workspace`);
    setWorkspaceFiles(files);
  }, [currentWorkspace]);

  useEffect(() => {
    loadWorkspaces();
    (async () => {
      try {
        const { models } = await apiGet('/api/ollama/models');
        setModels(models);
      } catch (_) { /* Ollama unreachable; user can still type a model name */ }
    })();
  }, [loadWorkspaces]);

  useEffect(() => { refreshWorkspaceFiles(); }, [currentWorkspace, refreshWorkspaceFiles]);

  return {
    workspaces, currentWorkspace, setCurrentWorkspace, createWorkspace,
    workspaceFiles, refreshWorkspaceFiles, models,
  };
}
