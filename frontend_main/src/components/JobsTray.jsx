import { useJobs } from '../context/JobsContext'

function StatusDot({ status }) {
  const color = status === 'running' ? 'var(--purple)' : status === 'done' ? 'var(--ok)' : 'var(--err)'
  return (
    <span
      className={status === 'running' ? 'job-status-dot job-status-dot-pulse' : 'job-status-dot'}
      style={{ background: color }}
    />
  )
}

export default function JobsTray() {
  const { jobs, dismissJob } = useJobs()
  const entries = Object.values(jobs).sort((a, b) => (a.id < b.id ? 1 : -1))

  if (entries.length === 0) return null

  return (
    <div className="jobs-tray">
      {entries.map(job => {
        const lastMsg = job.progress?.[job.progress.length - 1]
        const retrying = job.progress?.some(p => p.toLowerCase().includes('token limit')) && job.status === 'running'
        return (
          <div key={job.id} className="jobs-tray-card">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', fontWeight: 600, minWidth: 0, overflowWrap: 'break-word' }}>
                <StatusDot status={job.status} />
                {job.label}
              </div>
              {job.status !== 'running' && (
                <button
                  onClick={() => dismissJob(job.id)}
                  className="btn small ghost"
                  style={{ padding: '2px 7px', flexShrink: 0 }}
                >×</button>
              )}
            </div>
            {retrying && (
              <div style={{ marginTop: 4, color: 'var(--warn)', fontWeight: 600 }}>
                Token limit hit — clearing context and retrying…
              </div>
            )}
            {!retrying && lastMsg && job.status === 'running' && (
              <div style={{ marginTop: 4, color: 'var(--text-muted)' }}>{lastMsg}</div>
            )}
            {job.status === 'done' && job.result?.status === 'ok' && (
              <div style={{ marginTop: 4, color: '#1e9e5c' }}>
                Done{job.result.attempts > 1 ? ` (after ${job.result.attempts} attempts)` : ''}.
              </div>
            )}
            {job.status === 'done' && job.result?.status === 'error' && (
              <div style={{ marginTop: 4, color: 'var(--err)' }}>{job.result.error || 'Finished with errors.'}</div>
            )}
            {job.status === 'error' && (
              <div style={{ marginTop: 4, color: 'var(--err)' }}>{job.error}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}
