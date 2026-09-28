import { useCallback, useEffect, useMemo, useState } from 'react'
import { extractErrorMessage, listFiles, startCoaiderSession } from '../api/client'
import TerminalView from '../components/TerminalView'

const formatSize = (bytes = 0) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/**
 * A focused Coaider workspace.  Coaider deliberately uses the same isolated
 * PTY transport as Modularization and Test Case Generation: the terminal is
 * therefore a real Aider session rather than a styled transcript.
 */
export default function CoaiderConsole({ currentWorkspace, onCreateWorkspace }) {
  const [files, setFiles] = useState([])
  const [selectedFiles, setSelectedFiles] = useState([])
  const [prompt, setPrompt] = useState('Review the selected files and help me make a safe, focused improvement.')
  const [sessionId, setSessionId] = useState(null)
  const [starting, setStarting] = useState(false)
  const [ended, setEnded] = useState(false)
  const [changedFiles, setChangedFiles] = useState([])
  const [error, setError] = useState('')

  const refreshFiles = useCallback(async () => {
    if (!currentWorkspace) return
    try {
      setFiles(await listFiles(currentWorkspace))
    } catch (err) {
      setError(extractErrorMessage(err))
    }
  }, [currentWorkspace])

  useEffect(() => {
    setSessionId(null)
    setEnded(false)
    setChangedFiles([])
    setError('')
    setSelectedFiles([])
    refreshFiles()
  }, [currentWorkspace, refreshFiles])

  const selectedSize = useMemo(() => files
    .filter((file) => selectedFiles.includes(file.name))
    .reduce((total, file) => total + (file.size_bytes || 0), 0), [files, selectedFiles])

  const toggleFile = (name) => setSelectedFiles((previous) => (
    previous.includes(name) ? previous.filter((file) => file !== name) : [...previous, name]
  ))

  const startSession = async () => {
    if (!currentWorkspace || !selectedFiles.length || !prompt.trim()) return
    setStarting(true)
    setError('')
    setChangedFiles([])
    try {
      const result = await startCoaiderSession(currentWorkspace, selectedFiles, prompt.trim())
      setSessionId(result.session_id)
      setEnded(false)
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setStarting(false)
    }
  }

  if (!currentWorkspace) {
    return (
      <section className="coaider-empty">
        <span className="coaider-empty-icon">✦</span>
        <h2>Set up a workspace for Coaider</h2>
        <p>Choose or create a workspace from the Workspace tab before opening a live Aider terminal.</p>
        <button className="coaider-primary-button" type="button" onClick={() => onCreateWorkspace?.('coaider-workspace')}>Create workspace</button>
      </section>
    )
  }

  return (
    <section className="coaider-console" aria-label="Coaider live coding workspace">
      <aside className="coaider-rail">
        <div className="coaider-product-row">
          <div className="coaider-product-icon">✦</div>
          <div>
            <p className="coaider-kicker">Active workspace</p>
            <h2>{currentWorkspace}</h2>
            <span>Live Aider session</span>
          </div>
        </div>

        <section className="coaider-rail-section coaider-engine-card">
          <div className="coaider-section-heading"><span>Inference engine</span><b>Ready</b></div>
          <div className="coaider-engine-name"><span>✦</span> Aider PTY</div>
          <p>Interactive session shared with Modularization and Test Case Generation.</p>
          <div className="coaider-mode-row" aria-label="Aider mode">
            <button type="button" className="active">Code</button><button type="button">Architect</button><button type="button">Ask</button>
          </div>
        </section>

        <section className="coaider-rail-section coaider-context-card">
          <div className="coaider-section-heading"><span>Context budget</span><b>{selectedFiles.length} files</b></div>
          <div className="coaider-context-number">{formatSize(selectedSize)} <span>selected</span></div>
          <div className="coaider-meter"><i style={{ width: `${Math.min(100, selectedFiles.length * 18)}%` }} /></div>
          <p>Select only files relevant to the task for a focused, efficient Aider context.</p>
        </section>

        <section className="coaider-rail-section coaider-files-card">
          <div className="coaider-section-heading"><span>Active context</span><button type="button" onClick={refreshFiles}>↻ Refresh</button></div>
          <div className="coaider-file-list">
            {files.length === 0 && <p className="coaider-list-empty">No workspace files yet.</p>}
            {files.map((file) => {
              const selected = selectedFiles.includes(file.name)
              return <label className={`coaider-file-row${selected ? ' selected' : ''}`} key={file.name}>
                <input type="checkbox" checked={selected} onChange={() => toggleFile(file.name)} />
                <span className="coaider-file-glyph">{selected ? '●' : '○'}</span>
                <span className="coaider-file-name" title={file.name}>{file.name}</span>
                <small>{formatSize(file.size_bytes)}</small>
              </label>
            })}
          </div>
        </section>

        {changedFiles.length > 0 && <section className="coaider-rail-section coaider-changes-card">
          <div className="coaider-section-heading"><span>Changed files</span><b>+{changedFiles.length}</b></div>
          {changedFiles.map((file) => <div className="coaider-changed-file" key={file}>● <span>{file}</span></div>)}
        </section>}
      </aside>

      <main className="coaider-stage">
        <header className="coaider-stage-header">
          <div><p className="coaider-kicker">Coaider</p><h1>Build with a live terminal</h1></div>
          <div className={`coaider-live-status${sessionId && !ended ? ' is-live' : ''}`}><i />{sessionId && !ended ? 'Live / Ready' : 'Ready to start'}</div>
        </header>

        {!sessionId ? <div className="coaider-launch-card">
          <div className="coaider-terminal-placeholder"><span>$_</span><strong>Start an interactive Aider session</strong><p>Your commands, prompts, confirmations, and streamed output all use the shared PTY terminal.</p></div>
          <label htmlFor="coaider-prompt">Task for Aider</label>
          <textarea id="coaider-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Describe the change you want to make…" />
          {error && <p className="coaider-error" role="alert">{error}</p>}
          <div className="coaider-launch-actions"><span>{selectedFiles.length ? `${selectedFiles.length} file${selectedFiles.length === 1 ? '' : 's'} attached` : 'Select at least one file'}</span><button className="coaider-primary-button" type="button" onClick={startSession} disabled={starting || !selectedFiles.length || !prompt.trim()}>{starting ? 'Starting terminal…' : 'Start Coaider session →'}</button></div>
        </div> : <div className="coaider-terminal-card">
          <div className="coaider-terminal-chrome"><span><i /><i /><i /></span><b>aider — {currentWorkspace}</b><button type="button" onClick={() => { setSessionId(null); setEnded(false); setError(''); refreshFiles() }}>New session</button></div>
          <TerminalView sessionId={sessionId} onExit={(changes) => { setChangedFiles(changes); setEnded(true); refreshFiles() }} onError={setError} />
          {error && <p className="coaider-error" role="alert">{error}</p>}
        </div>}
      </main>
    </section>
  )
}
