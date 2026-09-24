import { useEffect, useRef, useState } from 'react'
import { getVisionModels, translateImage, extractErrorMessage } from '../api/client'

export default function ImageTranslatePanel({ languages }) {
  const [file, setFile] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [visionModels, setVisionModels] = useState([])
  const [model, setModel] = useState('')
  const [targetLang, setTargetLang] = useState('en')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const fileInputRef = useRef(null)
  const previewUrlRef = useRef(null)

  useEffect(() => {
    getVisionModels().then(res => {
      setVisionModels(res.models)
      setModel(prev => prev || res.models?.[0]?.name || '')
    }).catch(() => {})
  }, [])

  // Revoke the previous object URL whenever it's replaced or on unmount,
  // so selecting several images in a row doesn't leak memory.
  useEffect(() => {
    previewUrlRef.current = previewUrl
  }, [previewUrl])
  useEffect(() => () => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
  }, [])

  const handleFileChange = (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
    setFile(f)
    setResult(null)
    setError(null)
    setPreviewUrl(URL.createObjectURL(f))
  }

  const handleAnalyze = async () => {
    if (!file || !model) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await translateImage(file, model, targetLang)
      setResult(res)
    } catch (e) {
      setError(extractErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  const targetLanguages = languages?.target_languages || []

  return (
    <div className="panel">
      <h3>Understand an Image</h3>
     
      <div className="image-translate-layout">
        <div className="image-translate-preview">
          {previewUrl ? (
            <img src={previewUrl} alt="Selected upload preview" className="image-preview-img" />
          ) : (
            <div className="image-preview-placeholder" onClick={() => fileInputRef.current?.click()}>
              Click to choose an image
            </div>
          )}
          <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={handleFileChange} />
          <button className="btn small ghost" style={{ marginTop: 8, width: '100%' }} onClick={() => fileInputRef.current?.click()}>
            {file ? 'Choose a different image' : 'Choose image'}
          </button>
        </div>

        <div className="image-translate-controls">
          <div className="grid-2">
            <div>
              <div className="section-label">Vision Model</div>
              <select className="select" style={{ width: '100%' }} value={model} onChange={e => setModel(e.target.value)}>
                {visionModels.length === 0 && <option value="">No vision models detected</option>}
                {visionModels.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
              </select>
            </div>
            <div>
              <div className="section-label">Understand Text In</div>
              <select className="select" style={{ width: '100%' }} value={targetLang} onChange={e => setTargetLang(e.target.value)}>
                {targetLanguages.map(l => <option key={l.code} value={l.code}>{l.name}</option>)}
              </select>
            </div>
          </div>

          <button className="btn primary" style={{ marginTop: 12 }} onClick={handleAnalyze} disabled={!file || !model || loading}>
            {loading ? <><span className="spinner" /> Analyzing image…</> : 'Analyze Image'}
          </button>

          {error && <div className="hint" style={{ color: 'var(--err)', marginTop: 8 }}>{error}</div>}

          {result && (
            <div style={{ marginTop: 14 }}>
              <div className="section-label">WHAT THE IMAGE SHOWS</div>
              <p style={{ fontSize: 13.5, lineHeight: 1.6, marginTop: 0 }}>{result.description}</p>

              {result.has_text ? (
                <>
                  <div className="section-label">DETECTED TEXT</div>
                  <div className="log-box" style={{ marginBottom: 10 }}>{result.detected_text}</div>
                  <div className="section-label">TRANSLATION</div>
                  <div className="log-box">{result.translation}</div>
                </>
              ) : (
                <div className="hint" style={{ marginBottom: 0 }}>No visible text was detected in this image.</div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
