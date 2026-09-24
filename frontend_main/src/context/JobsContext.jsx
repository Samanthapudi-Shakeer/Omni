import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { startFixAllJob, startTranslateOfficeDocJob, getJob } from '../api/client'

const JobsContext = createContext(null)

export function JobsProvider({ children }) {
  const [jobs, setJobs] = useState({}) // jobId -> job state
  const pollTimers = useRef({})

  const poll = useCallback((jobId) => {
    if (pollTimers.current[jobId]) return
    const tick = async () => {
      try {
        const data = await getJob(jobId)
        setJobs(prev => ({ ...prev, [jobId]: data }))
        if (data.status === 'running') {
          pollTimers.current[jobId] = setTimeout(tick, 1200)
        } else {
          delete pollTimers.current[jobId]
        }
      } catch {
        delete pollTimers.current[jobId]
      }
    }
    tick()
  }, [])

  useEffect(() => () => {
    Object.values(pollTimers.current).forEach(clearTimeout)
  }, [])

  const startFixAll = useCallback(async (workspace, issues) => {
    const { job_id } = await startFixAllJob(workspace, issues)
    setJobs(prev => ({ ...prev, [job_id]: { id: job_id, kind: 'fix_all', label: `Fix All (${issues.length} issues)`, status: 'running', progress: [] } }))
    poll(job_id)
    return job_id
  }, [poll])

  const startTranslateOfficeDoc = useCallback(async (kind, workspace, file, sourceLang, targetLang, model, visionModel) => {
    const { job_id } = await startTranslateOfficeDocJob(kind, workspace, file, sourceLang, targetLang, model, visionModel)
    setJobs(prev => ({ ...prev, [job_id]: { id: job_id, kind: `translate_${kind}`, label: `Translate ${kind.toUpperCase()}: ${file}`, status: 'running', progress: [] } }))
    poll(job_id)
    return job_id
  }, [poll])

  const dismissJob = useCallback((jobId) => {
    setJobs(prev => {
      const next = { ...prev }
      delete next[jobId]
      return next
    })
  }, [])

  return (
    <JobsContext.Provider value={{ jobs, startFixAll, startTranslateOfficeDoc, dismissJob }}>
      {children}
    </JobsContext.Provider>
  )
}

export function useJobs() {
  const ctx = useContext(JobsContext)
  if (!ctx) throw new Error('useJobs must be used inside a JobsProvider')
  return ctx
}
