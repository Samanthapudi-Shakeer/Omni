import { useCallback, useEffect, useState } from 'react';
import { apiGet } from '../api';

export function useWorkspaceFilesAndModels(currentWorkspace) {
  const [workspaceFiles, setWorkspaceFiles] = useState([]);
  const [models, setModels] = useState([]);

  const refreshWorkspaceFiles = useCallback(async () => {
    if (!currentWorkspace) { setWorkspaceFiles([]); return; }
    const { files } = await apiGet(`/api/ws/${encodeURIComponent(currentWorkspace)}/files/workspace`);
    setWorkspaceFiles(files);
  }, [currentWorkspace]);

  useEffect(() => {
    (async () => {
      try {
        const { models } = await apiGet('/api/ollama/models');
        setModels(models);
      } catch (_) { /* Ollama unreachable; not needed by the Aider-routed tools anyway */ }
    })();
  }, []);

  useEffect(() => { refreshWorkspaceFiles(); }, [currentWorkspace, refreshWorkspaceFiles]);

  return { workspaceFiles, refreshWorkspaceFiles, models };
}
