import { useEffect, useRef, useState } from 'react'
import { runAnalysis, uploadZip, askAI, getHowToFix, extractErrorMessage, getReportUrl } from '../api/client'
import { useJobs } from '../context/JobsContext'
import IssueRow from './IssueRow'
import AskAIModal from './AskAIModal'
import HowToFixModal from './HowToFixModal'
import FileHistoryModal from './FileHistoryModal'

export default function StaticAnalysisPanel({ workspace, attached, onFilesChanged }) {
  const { jobs, startFixAll } = useJobs()

  const [analyzing, setAnalyzing] = useState(false)
  const [issues, setIssues] = useState([])
  const [reportText, setReportText] = useState('')
  const [reportFile, setReportFile] = useState(null)
  const [dashboardUrl, setDashboardUrl] = useState(null)

  const [askIssue, setAskIssue] = useState(null)
  const [askLoading, setAskLoading] = useState(false)
  const [askExplanation, setAskExplanation] = useState('')

  // "How to Fix" is preview-first: opening it never changes anything on
  // disk. Only a successful "Apply this fix" inside the modal (tracked via
  // appliedByIssueId) marks an issue as fixed.
  const [howToFixIssue, setHowToFixIssue] = useState(null)
  const [howToFixLoading, setHowToFixLoading] = useState(false)
  const [howToFixResult, setHowToFixResult] = useState(null)
  const [howToFixError, setHowToFixError] = useState(null)
  const [appliedByIssueId, setAppliedByIssueId] = useState({}) // issueId -> {status, diff, commit}

  const [fixAllJobId, setFixAllJobId] = useState(null)
  const [historyFile, setHistoryFile] = useState(null)
  const [zipLoading, setZipLoading] = useState(false)
  const zipInputRef = useRef(null)

  const fixAllJob = fixAllJobId ? jobs[fixAllJobId] : null
  const fixAllRunning = fixAllJob?.status === 'running'

  // This panel stays mounted for the whole app lifetime (see App.jsx - tabs
  // are hidden with CSS, not unmounted), so switching to another tab and
  // back no longer clears anything here. A real workspace switch, though,
  // should still start fresh - stale issues/diffs from a different
  // workspace would be actively misleading.
  const isFirstRun = useRef(true)
  useEffect(() => {
    if (isFirstRun.current) { isFirstRun.current = false; return }
    setIssues([])
    setReportText('')
    setReportFile(null)
    setDashboardUrl(null)
    setAppliedByIssueId({})
    setFixAllJobId(null)
    setHistoryFile(null)
  }, [workspace])

  const handleRun = async () => {
    setAnalyzing(true)
    setIssues([])
    setReportText('')
    setDashboardUrl(null)
    setAppliedByIssueId({})
    setFixAllJobId(null)
    try {
      const res = await runAnalysis(workspace, [])
      setIssues(Array.isArray(res.issues) ? res.issues : [])
      setReportText(typeof res.report_text === 'string' ? res.report_text : 'Analysis returned no report.')
      setReportFile(res.report_file)
      setDashboardUrl(typeof res.dashboard_url === 'string' ? res.dashboard_url : null)
    } catch (e) {
      setReportText(`Failed to run analysis: ${extractErrorMessage(e)}`)
    } finally {
      setAnalyzing(false)
    }
  }

  const handleZipUpload = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setZipLoading(true)
    setReportText('')
    try {
      await uploadZip(workspace, file)
      onFilesChanged?.()
      await handleRun()
    } catch (e) {
      setReportText(`Failed to upload project ZIP: ${extractErrorMessage(e)}`)
    } finally {
      setZipLoading(false)
    }
  }

  const handleAsk = async (issue) => {
    setAskIssue(issue)
    setAskLoading(true)
    setAskExplanation('')
    try {
      const res = await askAI(workspace, issue)
      // Defensive: always coerce to a string before it reaches JSX - an
      // unexpected non-string shape here was a likely cause of the
      // "screen resets" crash (an uncaught render error unmounts the
      // whole app without an error boundary in the way).
      setAskExplanation(typeof res.explanation === 'string' ? res.explanation : String(res.explanation ?? ''))
    } catch (e) {
      setAskExplanation(`Could not get explanation: ${extractErrorMessage(e)}`)
    } finally {
      setAskLoading(false)
    }
  }

  const handleHowToFix = async (issue) => {
    setHowToFixIssue(issue)
    setHowToFixLoading(true)
    setHowToFixResult(null)
    setHowToFixError(null)
    try {
      const res = await getHowToFix(workspace, issue)
      setHowToFixResult(res)
    } catch (e) {
      setHowToFixError(extractErrorMessage(e))
    } finally {
      setHowToFixLoading(false)
    }
  }

  const handleFixApplied = (issue, applyResult) => {
    setAppliedByIssueId(prev => ({ ...prev, [issue.id]: applyResult }))
    onFilesChanged?.()
  }

  const handleFixAll = async () => {
    const jobId = await startFixAll(workspace, issues)
    setFixAllJobId(jobId)
  }

  // Once Fix All finishes, tell the sidebar to refresh file sizes/metadata.
  useEffect(() => {
    if (fixAllJobId && jobs[fixAllJobId]?.status === 'done') onFilesChanged?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs, fixAllJobId])

  const grouped = issues.reduce((acc, i) => {
    (acc[i.file] ||= []).push(i)
    return acc
  }, {})

  return (
    <div>
      <div className="panel">
        <h3>Static Code Analysis</h3>
        <div className="hint">
          SonarQube analyzes the uploaded project archive. Upload a ZIP here or in the workspace,
          then run the scan. "How to Fix" previews an explanation
          and a diff without changing anything - applying it is a separate, explicit step, and
          every applied fix is committed to that file's version history, so the <strong>History</strong>{' '}
          button on each file below always lets you browse every past fix and diff it against any
          earlier version (or the original, untouched baseline).
        </div>
        <input ref={zipInputRef} type="file" accept=".zip,application/zip" hidden onChange={handleZipUpload} />
        <button className="btn" onClick={() => zipInputRef.current?.click()} disabled={zipLoading || analyzing}>
          {zipLoading ? <><span className="spinner" /> Uploading…</> : 'Upload project ZIP'}
        </button>{' '}
        <button className="btn primary" onClick={handleRun} disabled={analyzing || zipLoading}>
          {analyzing ? <><span className="spinner" /> SonarQube scanning…</> : 'Run SonarQube analysis'}
        </button>
      </div>

      {issues.length > 0 && (
        <div className="panel" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <strong>{issues.length} issue{issues.length === 1 ? '' : 's'} found</strong>
            {fixAllRunning && (
              <div className="hint">{fixAllJob.progress?.[fixAllJob.progress.length - 1] || 'Fixing…'}</div>
            )}
            {fixAllJob?.status === 'done' && (
              <div className="hint">
                {fixAllJob.result.results.filter(r => r.status === 'ok').length}/{fixAllJob.result.results.length} fixed successfully.
              </div>
            )}
          </div>
          <button className="btn primary" onClick={handleFixAll} disabled={fixAllRunning}>
            {fixAllRunning ? <><span className="spinner" /> Fixing all…</> : `Fix All (${issues.length})`}
          </button>
        </div>
      )}

      {issues.length > 0 && Object.entries(grouped).map(([file, fileIssues]) => (
        <div className="panel" key={file}>
          <h3 style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            {file}
            <button className="btn small ghost" onClick={() => setHistoryFile(file)}>History</button>
          </h3>
          <div className="hint">{fileIssues.length} finding{fileIssues.length === 1 ? '' : 's'}</div>
          {fileIssues.map(issue => {
            // Individually-applied fixes (via the How to Fix modal) take
            // priority for display; otherwise fall back to a Fix All batch
            // result for the same issue, if any.
            const applied = appliedByIssueId[issue.id]
            const batchResult = fixAllJob?.result?.results?.find(r => r.issue_id === issue.id)
            const display = applied
              ? { status: 'ok', diff: applied.diff }
              : batchResult

            const fixed = display?.status === 'ok'

            return (
              <div key={issue.id}>
                <IssueRow
                  issue={issue}
                  onAsk={handleAsk}
                  onHowToFix={handleHowToFix}
                  fixDisabled={fixAllRunning}
                  fixed={fixed}
                />
                {display && (
                  <div style={{ margin: '4px 0 14px 19px' }}>
                    {display.status === 'ok' ? (
                      <span className="status-pill status-ok">
                        ✓ Fixed{display.diff === '' ? ' — no change needed' : ''}
                      </span>
                    ) : (
                      <span className="status-pill status-error">Failed: {display.error || 'unknown error'}</span>
                    )}
                    {display.diff && (
                      <div className="diff-box" style={{ marginTop: 6 }}>{display.diff}</div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ))}

      {issues.length === 0 && !analyzing && reportText === '' && (
        <div className="panel"><div className="empty-state">No analysis run yet.</div></div>
      )}

      {reportText && (
        <div className="panel">
          {dashboardUrl && (
            <div style={{ marginBottom: 12 }}>
              <strong>SonarQube Dashboard: </strong>
              <a href={dashboardUrl} target="_blank" rel="noreferrer">
                Open project dashboard
              </a>
            </div>
          )}
          <h3 style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            AI Summary Report
            {reportFile && (
              <a className="btn small" href={getReportUrl(workspace, reportFile)} download={reportFile}>
                Download .txt
              </a>
            )}
          </h3>
          <div className="log-box">{reportText}</div>
        </div>
      )}

      <AskAIModal
        issue={askIssue}
        explanation={askExplanation}
        loading={askLoading}
        onClose={() => setAskIssue(null)}
      />

      <HowToFixModal
        workspace={workspace}
        issue={howToFixIssue}
        result={howToFixResult}
        loading={howToFixLoading}
        error={howToFixError}
        onClose={() => setHowToFixIssue(null)}
        onApplied={handleFixApplied}
      />

      {historyFile && (
        <FileHistoryModal
          workspace={workspace}
          filename={historyFile}
          onClose={() => setHistoryFile(null)}
        />
      )}
    </div>
  )
}
