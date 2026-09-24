import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// Safely turns any axios error (or plain Error) into a displayable string.
// FastAPI validation errors put an ARRAY of objects in response.data.detail
// rather than a string - rendering that shape directly as a JSX child (or
// relying on implicit coercion in the wrong spot) is a classic source of an
// uncaught "Objects are not valid as a React child" crash, which React
// responds to by tearing down the whole component tree - i.e. exactly the
// "screen resets, data is lost" symptom. Every error-handling call site in
// this app should go through this helper instead of touching
// `e.response.data.detail` directly.
export function extractErrorMessage(e) {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map(d => (typeof d === 'string' ? d : d?.msg || JSON.stringify(d)))
      .join('; ')
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return e?.message || 'Unknown error'
}

export const listFiles = (workspace) =>
  api.get(`/workspace/${encodeURIComponent(workspace)}/files`).then(r => r.data)

export const uploadFile = (workspace, file) => {
  const form = new FormData()
  form.append('file', file)
  return api.post(`/workspace/${encodeURIComponent(workspace)}/upload`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

export const uploadZip = (workspace, file) => {
  const form = new FormData()
  form.append('file', file)
  return api.post(`/workspace/${encodeURIComponent(workspace)}/upload-zip`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

export const createWorkspaceFile = (workspace, name, content = '') =>
  api.post(`/workspace/${encodeURIComponent(workspace)}/file`, { name, content }).then(r => r.data)

export const deleteWorkspaceFile = (workspace, filename) =>
  api.delete(`/workspace/${encodeURIComponent(workspace)}/file/${encodeURIComponent(filename)}`).then(r => r.data)

export const runAnalysis = (workspace, files) =>
  api.post('/analysis/run', { workspace, files }).then(r => r.data)

export const askAI = (workspace, issue) =>
  api.post('/analysis/ask', { workspace, issue }).then(r => r.data)

// "How to Fix" is preview-only: supplies the WHOLE file as context and
// returns an explanation + a suggested diff. Nothing is written to disk -
// call applyFix() separately (and only) if the user clicks "Apply this fix".
export const getHowToFix = (workspace, issue, model) =>
  api.post('/analysis/how-to-fix', { workspace, issue, model }).then(r => r.data)

// Writes exactly the previously-previewed fix (start_line/end_line/fixed_code
// must come from a prior getHowToFix() response) and commits it to the
// file's version history. No Ollama call happens here.
export const applyFix = (workspace, issue, startLine, endLine, fixedCode) =>
  api.post('/analysis/apply-fix', {
    workspace, issue, start_line: startLine, end_line: endLine, fixed_code: fixedCode,
  }).then(r => r.data)

// Fix All is a background job: this call only starts the job and returns
// { job_id }. Poll getJob() (or use JobsContext) for progress/result - this
// is what lets a token-limit retry keep running without the request itself
// timing out or the UI resetting.
export const startFixAllJob = (workspace, issues) =>
  api.post('/analysis/fix-all', { workspace, issues }).then(r => r.data)

// Modularization is now a live interactive PTY session (same mechanism as
// Test Case Generation), not a background job - returns { session_id };
// connect a TerminalView to it via the shared /api/pty/ws endpoint.
export const startModularizeSession = (workspace, file, prompt) =>
  api.post('/modularize/start-session', { workspace, file, prompt }).then(r => r.data)

export const getJob = (jobId) =>
  api.get(`/jobs/${encodeURIComponent(jobId)}`).then(r => r.data)

export const getReportUrl = (workspace, reportFile) =>
  `/api/analysis/report/${encodeURIComponent(workspace)}/${encodeURIComponent(reportFile)}`

export const getDefaultModularizePrompt = () =>
  api.get('/modularize/default-prompt').then(r => r.data.prompt)

// ------------------------------------------------------------- static analysis history
export const getFileHistory = (workspace, filename) =>
  api.get(`/analysis/history/${encodeURIComponent(workspace)}/${encodeURIComponent(filename)}`).then(r => r.data)

export const getFileDiff = (workspace, filename, params = {}) =>
  api.get(`/analysis/diff/${encodeURIComponent(workspace)}/${encodeURIComponent(filename)}`, { params }).then(r => r.data)

// ------------------------------------------------------------------ test case generation
export const getDefaultTestGenPrompt = () =>
  api.get('/testgen/default-prompt').then(r => r.data.prompt)

// Returns { session_id }. Connect a WebSocket to /api/testgen/ws/{session_id}
// (see components/TerminalView.jsx) for the live interactive terminal.
export const startTestGenSession = (workspace, files, prompt) =>
  api.post('/testgen/start', { workspace, files, prompt }).then(r => r.data)

// ------------------------------------------------------------------ translate
export const getTranslateLanguages = () =>
  api.get('/translate/languages').then(r => r.data)

export const getTranslateModels = () =>
  api.get('/translate/models').then(r => r.data)

export const getVisionModels = () =>
  api.get('/translate/vision-models').then(r => r.data)

// Standalone image upload (not tied to any workspace file): returns a
// description of what the image shows plus, if it contains visible text,
// that text and its translation. Single stateless vision-model call.
export const translateImage = (file, model, targetLang) => {
  const form = new FormData()
  form.append('file', file)
  form.append('model', model)
  form.append('target_lang', targetLang)
  return api.post('/translate/image', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

// Each call is a standalone, stateless translation - no shared context with
// any previous call, so rapid retranslation/swap never bleeds state across
// requests.
export const translateText = (text, sourceLang, targetLang, model) =>
  api.post('/translate', { text, source_lang: sourceLang, target_lang: targetLang, model }).then(r => r.data)

// Background job (can involve many Ollama calls for a large document) -
// returns { job_id }, poll via getJob() / JobsContext same as fix/modularize
// jobs. `kind` is 'pptx' | 'docx' | 'xlsx'.
export const startTranslateOfficeDocJob = (kind, workspace, file, sourceLang, targetLang, model, visionModel) =>
  api.post(`/translate/${kind}`, {
    workspace, file, source_lang: sourceLang, target_lang: targetLang,
    model, vision_model: visionModel || null,
  }).then(r => r.data)

export default api
