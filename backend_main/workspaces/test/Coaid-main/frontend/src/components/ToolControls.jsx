import React from 'react';
import WorkspaceBar from './WorkspaceBar';

export default function ToolControls({
  workspaces, currentWorkspace, onSelectWorkspace, onCreateWorkspace,
  workspaceFiles, selectedFile, onSelectFile, selectedFiles, onSelectFiles,
  models, selectedModel, onSelectModel, showModel = true,
}) {
  return (
    <div className="tool-controls">
      <WorkspaceBar
        workspaces={workspaces}
        current={currentWorkspace}
        onSelect={onSelectWorkspace}
        onCreate={onCreateWorkspace}
      />
      <div className="field">
        <label>File</label>
        <select value={selectedFile} onChange={(e) => onSelectFile(e.target.value)} disabled={!currentWorkspace}>
          {workspaceFiles.length === 0 && <option value="">No files in this workspace</option>}
          {workspaceFiles.map((f) => <option key={f.path} value={f.path}>{f.path}</option>)}
        </select>
      </div>
      {showModel && (
        <div className="field">
          <label>Ollama model</label>
          <select value={selectedModel} onChange={(e) => onSelectModel(e.target.value)}>
            {models.length === 0 && <option value="">No models found</option>}
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
      )}
    </div>
  );
}
