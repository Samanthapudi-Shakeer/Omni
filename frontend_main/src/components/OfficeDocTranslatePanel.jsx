import { useEffect, useRef, useState } from 'react'
import { getVisionModels, extractErrorMessage } from '../api/client'
import { useJobs } from '../context/JobsContext'

// kind: 'pptx' | 'docx' | 'xlsx' — drives which endpoint is called and
// which attached files are offered.
export default function OfficeDocTranslatePanel({
  kind, extension, title, description, statLabels,
  workspace, attached, languages, models, defaultModel, onFilesChanged,
}) {
  const { jobs, startTranslateOfficeDoc } = useJobs()

  const matchingFiles = attached.filter(f => f.name.toLowerCase().endsWith(extension))
  const [selectedFile, setSelectedFile] = useState('')
  const [sourceLang, setSourceLang] = useState('auto')
  const [targetLang, setTargetLang] = useState('en')
  const [model, setModel] = useState('')
  const [visionModel, setVisionModel] = useState('') // '' = skip images
  const [visionModels, setVisionModels] = useState([])
  const [jobId, setJobId] = useState(null)
  const [startError, setStartError] = useState(null)

  useEffect(() => {
    getVisionModels().then(res => setVisionModels(res.models)).catch(() => {})
  }, [])

  useEffect(() => {
    if (!model && defaultModel) setModel(defaultModel)
  }, [defaultModel, model])

  // This panel stays mounted app-wide (tabs are CSS-hidden, not unmounted -
  // see App.jsx), so a tab switch alone never touches it. Only clear the
  // job reference on an actual workspace change - a "Done, download here"
  // result pointing at a different workspace's file would be misleading.
  const isFirstRun = useRef(true)
  useEffect(() => {
    if (isFirstRun.current) { isFirstRun.current = false; return }
    setJobId(null)
  }, [workspace])

  useEffect(() => {
    if (!selectedFile && matchingFiles.length > 0) setSelectedFile(matchingFiles[0].name)
    if (selectedFile && !matchingFiles.find(f => f.name === selectedFile)) {
      setSelectedFile(matchingFiles[0]?.name || '')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attached])

  const job = jobId ? jobs[jobId] : null
  const running = job?.status === 'running'

  const handleStart = async () => {
    if (!selectedFile) return
    setStartError(null)
    try {
      const id = await startTranslateOfficeDoc(kind, workspace, selectedFile, sourceLang, targetLang, model, visionModel || null)
      setJobId(id)
    } catch (e) {
      // Previously unguarded - a failed request here became a silent,
      // unhandled promise rejection with no visible feedback at all.
      setStartError(extractErrorMessage(e))
    }
  }

  useEffect(() => {
    if (job?.status === 'done' && job.result?.status === 'ok') onFilesChanged?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status])

  return (
    <div className="panel">
      <h3>{title}</h3>
      <div className="hint">{description}</div>

      {matchingFiles.length === 0 ? (
        <div className="empty-state">Attach a {extension} file in the sidebar to understand it.</div>
      ) : (
        <>
          <div className="section-label">FILE</div>
          <select className="select" style={{ width: '100%', marginBottom: 10 }}
            value={selectedFile} onChange={e => setSelectedFile(e.target.value)}>
            {matchingFiles.map(f => <option key={f.name} value={f.name}>{f.name}</option>)}
          </select>

          <div className="grid-2" style={{ marginBottom: 10 }}>
            <div>
              <div className="section-label">SOURCE LANGUAGE</div>
              <select className="select" style={{ width: '100%' }} value={sourceLang} onChange={e => setSourceLang(e.target.value)}>
                {languages.source_languages.map(l => <option key={l.code} value={l.code}>{l.name}</option>)}
              </select>
            </div>
            <div>
              <div className="section-label">TARGET LANGUAGE</div>
              <select className="select" style={{ width: '100%' }} value={targetLang} onChange={e => setTargetLang(e.target.value)}>
                {languages.target_languages.map(l => <option key={l.code} value={l.code}>{l.name}</option>)}
              </select>
            </div>
          </div>

          <div className="grid-2" style={{ marginBottom: 10 }}>
            <div>
              <div className="section-label">TEXT MODEL</div>
              <select className="select" style={{ width: '100%' }} value={model} onChange={e => setModel(e.target.value)}>
                {models.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
              </select>
            </div>
            <div>
              <div className="section-label">IMAGE TEXT (VISION MODEL)</div>
              <select className="select" style={{ width: '100%' }} value={visionModel} onChange={e => setVisionModel(e.target.value)}>
                <option value="">Skip images (text only)</option>
                {visionModels.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
              </select>
            </div>
          </div>

          <button className="btn primary" onClick={handleStart} disabled={running || !selectedFile}>
            {running ? <><span className="spinner" /> Translating…</> : `Translate ${extension.slice(1).toUpperCase()}`}
          </button>
          {startError && <div className="hint" style={{ color: 'var(--err)', marginTop: 8 }}>{startError}</div>}

          {job && (
            <div style={{ marginTop: 12 }}>
              {running && (
                <div className="hint">{job.progress?.[job.progress.length - 1] || 'Working…'}</div>
              )}
              {job.status === 'done' && job.result?.status === 'ok' && (
                <>
                  <div className="hint" style={{ color: '#1e9e5c' }}>
                    Done — {statLabels(job.result)}
                  </div>
                  <a
                    className="btn small primary"
                    style={{ marginTop: 6, display: 'inline-block' }}
                    href={`/api/workspace/${encodeURIComponent(workspace)}/download/${encodeURIComponent(job.result.output_file)}`}
                    download={job.result.output_file}
                  >
                    Download {job.result.output_file}
                  </a>
                </>
              )}
              {job.status === 'error' && (
                <div className="hint" style={{ color: 'var(--err)' }}>{job.error}</div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
