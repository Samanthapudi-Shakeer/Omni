import { useCallback, useEffect, useState } from 'react'
import Sidebar from './components/Sidebar'
import StaticAnalysisPanel from './components/StaticAnalysisPanel'
import ModularizationPanel from './components/ModularizationPanel'
import TestCaseGenPanel from './components/TestCaseGenPanel'
import TranslatePanel from './components/TranslatePanel'
import DiffKitPanel from './components/DiffKitPanel'
import ErrorBoundary from './components/ErrorBoundary'
import JobsTray from './components/JobsTray'
import { JobsProvider } from './context/JobsContext'
import { listFiles } from './api/client'
import { deleteWorkspaceFile, extractErrorMessage } from './api/client'
import FileHistoryModal from './components/FileHistoryModal'
import WorkspaceManager from './components/WorkspaceManager'

const TABS = [
  { id: 'workspace', label: 'Workspace'},
  { id: 'coaider', label: 'Coaider'},
  { id: 'analysis', label: 'Static Code Analysis' },
  { id: 'modularize', label: 'Modularization' },
  { id: 'testgen', label: 'Test Case Generation' },
  { id: 'translate', label: 'Requirement Understanding' },
  { id: 'diffkit', label: 'Diff Kit' },
]

export default function App() {
  const [workspace, setWorkspace] = useState('test')
  const [files, setFiles] = useState([])
  const [attached, setAttached] = useState([])
  const [tab, setTab] = useState('analysis')
  const [historyFile, setHistoryFile] = useState(null)

  const refreshFiles = useCallback(() => {
    listFiles(workspace).then(setFiles).catch(() => setFiles([]))
  }, [workspace])

  useEffect(() => {
    refreshFiles()
    setAttached([])
  }, [workspace, refreshFiles])

  const toggleAttach = (file) => {
    setAttached(prev =>
      prev.find(f => f.name === file.name)
        ? prev.filter(f => f.name !== file.name)
        : [...prev, file]
    )
  }

  return (
    <JobsProvider>
      <div className="app-shell">
        <ErrorBoundary label="Sidebar">
          <Sidebar
            workspace={workspace}
            setWorkspace={setWorkspace}
            files={files}
            refreshFiles={refreshFiles}
            attached={attached}
            toggleAttach={toggleAttach}
            clearAttached={() => setAttached([])}
            onShowHistory={setHistoryFile}
            onDelete={async file => {
              if (!window.confirm(`Delete ${file.name}? This cannot be undone.`)) return
              try { await deleteWorkspaceFile(workspace, file.name); setAttached(a => a.filter(x => x.name !== file.name)); refreshFiles() }
              catch (e) { window.alert(extractErrorMessage(e)) }
            }}
          />
        </ErrorBoundary>
        <div className="main">
          <div className="topbar">
            <div className="tab-group">
              {TABS.map(t => (
                <button
                  key={t.id}
                  className={`tab-btn ${tab === t.id ? 'active' : ''}`}
                  onClick={() => setTab(t.id)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="spacer" />
            <span className="badge">{workspace}</span>
          </div>
          <div className="content">
            
            <div data-testid="tab-panel-analysis" style={{ display: tab === 'analysis' ? 'block' : 'none' }}>
              <ErrorBoundary label="Static Analysis">
                <StaticAnalysisPanel workspace={workspace} attached={attached} onFilesChanged={refreshFiles} />
              </ErrorBoundary>
            </div>
            <div data-testid="tab-panel-workspace" style={{ display: tab === 'workspace' ? 'block' : 'none' }}>
              <WorkspaceManager workspace={workspace} files={files} refreshFiles={refreshFiles} />
            </div>
            <div data-testid="tab-panel-modularize" style={{ display: tab === 'modularize' ? 'block' : 'none' }}>
              <ErrorBoundary label="Modularization">
                <ModularizationPanel workspace={workspace} attached={attached} onFilesChanged={refreshFiles} />
              </ErrorBoundary>
            </div>
            <div data-testid="tab-panel-testgen" style={{ display: tab === 'testgen' ? 'block' : 'none' }}>
              <ErrorBoundary label="Test Case Generation">
                <TestCaseGenPanel workspace={workspace} attached={attached} onFilesChanged={refreshFiles} />
              </ErrorBoundary>
            </div>
            <div data-testid="tab-panel-translate" style={{ display: tab === 'translate' ? 'block' : 'none' }}>
              <ErrorBoundary label="Translate">
                <TranslatePanel workspace={workspace} attached={attached} onFilesChanged={refreshFiles} />
              </ErrorBoundary>
            </div>
            <div data-testid="tab-panel-diffkit" style={{ display: tab === 'diffkit' ? 'block' : 'none' }}>
              <ErrorBoundary label="Diff Kit">
                <DiffKitPanel />
              </ErrorBoundary>
            </div>
          </div>
        </div>
        {/* Rendered once at the app root (not inside either panel) so job
            progress - including token-limit retries - keeps updating in
            place no matter which tab is active or re-rendered. */}
        <ErrorBoundary label="Jobs tray">
          <JobsTray />
        </ErrorBoundary>
        <FileHistoryModal workspace={workspace} filename={historyFile} onClose={() => setHistoryFile(null)} />
      </div>
    </JobsProvider>
  )
}
