import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiGet, apiPost, apiUpload } from './api';
import { useAiderSocket } from './useAiderSocket';
import Sidebar from './components/Sidebar';
import WorkspaceBar from './components/WorkspaceBar';
import StatusBar from './components/StatusBar';
import TerminalView from './components/TerminalView';
import SupervisedView from './components/SupervisedView';
import Composer from './components/Composer';
import QuestionPrompt from './components/QuestionPrompt';
import Toasts from './components/Toasts';
import CommandPalette from './components/CommandPalette';
import RenameDownloadModal from './components/RenameDownloadModal';
import CodeCanvas from './components/CodeCanvas';

const DEFAULT_AIDER = {
  status: 'stopped',
  lastError: null,
  model: '',
  mode: 'code',
  workspace: '',
  attachedFiles: [],
  pendingQuestion: null,
  supervised: false,
  taskRunning: false,
};

let toastId = 0;

function b64ToUint8(b64) {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}

export default function App({ workspaces, currentWorkspace, onSelectWorkspace, onCreateWorkspace }) {
  const [aider, setAider] = useState(DEFAULT_AIDER);
  const [ollamaConnected, setOllamaConnected] = useState(false);
  const [ollamaError, setOllamaError] = useState(null);
  const [wsState, setWsState] = useState('connecting');
  const [models, setModels] = useState([]);
  const [workspaceFiles, setWorkspaceFiles] = useState([]);
  const [attachedFiles, setAttachedFiles] = useState([]);
  const [tokensSummary, setTokensSummary] = useState(null);
  const [modifiedFiles, setModifiedFiles] = useState([]);
  const [history, setHistory] = useState([]);
  const [transcript, setTranscript] = useState([]);
  const [phaseTimeline, setPhaseTimeline] = useState([]);
  const [fileProgress, setFileProgress] = useState({});
  const [taskStartedAt, setTaskStartedAt] = useState(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [lastTaskText, setLastTaskText] = useState('');
  const [prefillText, setPrefillText] = useState('');
  const [prefillNonce, setPrefillNonce] = useState(0);
  const [codeCanvas, setCodeCanvas] = useState({ open: false, file: null, files: [] });
  const [lastTaskResult, setLastTaskResult] = useState(null);
  const [viewMode, setViewMode] = useState('terminal'); // 'terminal' | 'supervised'
  const [composerText, setComposerText] = useState('');
  const [toasts, setToasts] = useState([]);
  const [commands, setCommands] = useState([]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [downloadTarget, setDownloadTarget] = useState(null); // path pending rename+download

  const writeRef = useRef(null);
  const rawBufferRef = useRef([]);

  const wsApi = useCallback((path) => `/api/ws/${encodeURIComponent(currentWorkspace)}${path}`, [currentWorkspace]);

  const toast = useCallback((message, kind = 'info') => {
    // Backward-compatible: some call sites still pass `true` for "error".
    const resolvedKind = kind === true ? 'error' : kind === false ? 'info' : kind;
    const id = ++toastId;
    setToasts((t) => [...t, { id, message, kind: resolvedKind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);

  // ------------------------------------------------------------------ notifications
  const beep = useCallback(() => {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.06, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
      osc.start();
      osc.stop(ctx.currentTime + 0.25);
    } catch (_) { /* audio not available; silently skip */ }
  }, []);

  const notify = useCallback((title, body, kind = 'info') => {
    beep();
    try {
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification(title, { body });
      }
    } catch (_) { /* notifications not available; the beep + toast still fire */ }
    toast(`${title}${body ? ` — ${body}` : ''}`, kind);
  }, [beep, toast]);

  useEffect(() => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {});
    }
  }, []);

  // ------------------------------------------------------------------ workspaces
  // Workspace list/selection is owned by Shell (shared across all four pages)
  // and passed down as props: workspaces, currentWorkspace, onSelectWorkspace,
  // onCreateWorkspace.

  useEffect(() => {
    (async () => {
      try {
        const { commands } = await apiGet('/api/commands');
        setCommands(commands);
      } catch (_) { /* command library is optional */ }
    })();
    (async () => {
      try {
        const { models } = await apiGet('/api/ollama/models');
        setModels(models);
      } catch (_) { /* handled by status polling too */ }
    })();
  }, []);

  useEffect(() => {
    setAider(DEFAULT_AIDER);
    setAttachedFiles([]);
    setWorkspaceFiles([]);
    setTokensSummary(null);
    setModifiedFiles([]);
    setHistory([]);
    setTranscript([]);
    setPhaseTimeline([]);
    setFileProgress({});
    setTaskStartedAt(null);
    setElapsedSeconds(0);
    setLastTaskResult(null);
    rawBufferRef.current = [];
  }, [currentWorkspace]);

  // ------------------------------------------------------------------ status / files
  const refreshStatus = useCallback(async () => {
    if (!currentWorkspace) return;
    try {
      const s = await apiGet(wsApi('/status'));
      setAider(s.aider);
      setAttachedFiles(s.aider.attachedFiles || []);
      setOllamaConnected(s.ollama.connected);
      setOllamaError(s.ollama.error);
      if (s.tokens) setTokensSummary(s.tokens);
      if (s.modifiedFiles) setModifiedFiles(s.modifiedFiles);
      if (s.fileProgress) setFileProgress(s.fileProgress);
      if (s.aider.lastError) toast(s.aider.lastError, 'error');
    } catch (err) {
      toast(`Status check failed: ${err.message}`, 'error');
    }
  }, [currentWorkspace, wsApi, toast]);

  const refreshWorkspaceFiles = useCallback(async () => {
    if (!currentWorkspace) return;
    try {
      const { files } = await apiGet(wsApi('/files/workspace'));
      setWorkspaceFiles(files);
    } catch (err) {
      toast(`Could not list workspace files: ${err.message}`, 'error');
    }
  }, [currentWorkspace, wsApi, toast]);

  const refreshHistory = useCallback(async () => {
    if (!currentWorkspace) return;
    try {
      const { history } = await apiGet(wsApi('/history'));
      setHistory(history);
    } catch (err) {
      toast(`Could not load version history: ${err.message}`, 'error');
    }
  }, [currentWorkspace, wsApi, toast]);

  useEffect(() => {
    if (!currentWorkspace) return undefined;
    refreshStatus();
    refreshWorkspaceFiles();
    refreshHistory();
    const interval = setInterval(() => {
      refreshStatus();
      refreshHistory();
    }, 8000);
    return () => clearInterval(interval);
  }, [currentWorkspace, refreshStatus, refreshWorkspaceFiles, refreshHistory]);

  // ------------------------------------------------------------------ WebSocket
  useAiderSocket(currentWorkspace, {
    onOpen: () => setWsState('live'),
    onClose: () => setWsState('down'),
    onMessage: (msg) => {
      switch (msg.type) {
        case 'raw': {
          const bytes = b64ToUint8(msg.data);
          rawBufferRef.current.push(bytes);
          if (rawBufferRef.current.length > 3000) rawBufferRef.current.shift();
          writeRef.current?.(bytes);
          break;
        }
        case 'status':
          setAider(msg.data);
          setAttachedFiles(msg.data.attachedFiles || []);
          if (msg.data.lastError) toast(msg.data.lastError, 'error');
          break;
        case 'files':
          setAttachedFiles(msg.data);
          break;
        case 'tokens':
          setTokensSummary(msg.data);
          break;
        case 'modified_files':
          setModifiedFiles(msg.data);
          refreshHistory();
          break;
        case 'phase':
          setPhaseTimeline((prev) => {
            // Dedupe consecutive repeats of the same label -- Aider often
            // re-triggers the same phase pattern many times in a row, and a
            // timeline of 40x "Editing files" isn't useful to look at.
            if (prev.length && prev[prev.length - 1].label === msg.data) return prev;
            const next = [...prev, { label: msg.data, at: Date.now() }];
            return next.length > 40 ? next.slice(-40) : next;
          });
          break;
        case 'transcript':
          setTranscript((prev) => {
            const next = [...prev, msg.data];
            return next.length > 200 ? next.slice(-200) : next;
          });
          break;
        case 'file_progress':
          setFileProgress(msg.data);
          break;
        case 'question':
          setAider((a) => ({ ...a, pendingQuestion: msg.data, status: 'waiting_input' }));
          notify('Aider needs your input', msg.data.question, 'info');
          break;
        case 'task_complete':
          setLastTaskResult(msg.data);
          notify('Task complete', `${msg.data.changedFiles.length} file(s) changed`, 'success');
          break;
        default:
          break;
      }
    },
  });

  // ------------------------------------------------------------------ context (client-side, instant)
  const contextStats = useMemo(() => {
    const attachedSet = new Set(attachedFiles);
    const totalBytes = workspaceFiles
      .filter((f) => attachedSet.has(f.path))
      .reduce((sum, f) => sum + (f.size || 0), 0);
    return { fileCount: attachedFiles.length, estTokens: Math.round(totalBytes / 4) };
  }, [attachedFiles, workspaceFiles]);

  // ------------------------------------------------------------------ elapsed timer
  useEffect(() => {
    if (!aider.taskRunning || !taskStartedAt) return undefined;
    const tick = () => setElapsedSeconds(Math.floor((Date.now() - taskStartedAt) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [aider.taskRunning, taskStartedAt]);

  // ------------------------------------------------------------------ actions
  async function guarded(action, successMsg) {
    try {
      await action();
      if (successMsg) toast(successMsg, 'success');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  const onStart = () => guarded(async () => setAider(await apiPost(wsApi('/aider/start'))), 'Starting Aider…');
  const onStop = () => guarded(async () => setAider(await apiPost(wsApi('/aider/stop'))), 'Aider stopped');
  const onRestart = () => guarded(
    async () => setAider(await apiPost(wsApi('/aider/restart'))),
    'Restarting Aider…'
  );
  const onClear = () => guarded(() => apiPost(wsApi('/aider/clear')), 'Chat history cleared');
  const onTokens = () => guarded(() => apiPost(wsApi('/aider/tokens')), 'Requested token usage report');
  const onModeChange = (mode) => guarded(async () => {
    await apiPost(wsApi('/aider/mode'), { mode });
    setAider((a) => ({ ...a, mode }));
  }, `Mode switched to ${mode}`);
  const onModelChange = (model) => guarded(async () => {
    await apiPost(wsApi('/aider/model'), { model });
    setAider((a) => ({ ...a, model }));
  }, `Switching model to ${model}`);
  const onAddFile = (path) => guarded(() => apiPost(wsApi('/files/add'), { path }), `Added ${path}`);
  const onDropFile = (path) => guarded(() => apiPost(wsApi('/files/drop'), { path }), `Dropped ${path}`);
  const onSendPrompt = (text) => guarded(async () => {
    await apiPost(wsApi('/aider/prompt'), { text });
    setComposerText('');
  });
  const onUpload = async (fileList) => {
    if (!fileList || fileList.length === 0) return;
    try {
      const form = new FormData();
      for (const f of fileList) form.append('files', f);
      const body = await apiUpload(wsApi('/upload'), form);
      toast(`Uploaded ${body.uploaded.length} file(s)`, 'success');
      refreshWorkspaceFiles();
    } catch (err) {
      toast(err.message, 'error');
    }
  };
  // Answering a question is the SAME action regardless of which mode
  // surfaced it -- both Terminal and Supervised render the same
  // QuestionPrompt component and call this single handler.
  const onAnswerQuestion = (text) => guarded(() => apiPost(wsApi('/aider/answer'), { text }), 'Answer sent');
  const onStartTask = (text, files) => guarded(async () => {
    setLastTaskResult(null);
    setTranscript([]);
    setPhaseTimeline([]);
    setFileProgress({});
    setTaskStartedAt(Date.now());
    setElapsedSeconds(0);
    setLastTaskText(text);
    setAider(await apiPost(wsApi('/task/start'), { text, files }));
  }, 'Task started');
  const onStopTask = () => guarded(() => apiPost(wsApi('/task/stop')), 'Task stopped');
  const onExecuteCommand = (cmd) => guarded(() => apiPost(wsApi('/aider/command'), { command: cmd }), `Ran ${cmd}`);
  const onInsertCommand = (text) => setComposerText((prev) => (prev ? prev + ' ' + text : text));
  const onFollowUp = () => {
    setPrefillText(`Following up on "${lastTaskText}": `);
    setPrefillNonce((n) => n + 1);
  };

  // ------------------------------------------------------------------ Code Canvas
  const encodePath = (p) => p.split('/').map(encodeURIComponent).join('/');
  const fetchFileVersions = useCallback(async (path) => {
    const { versions } = await apiGet(wsApi(`/files/versions/${encodePath(path)}`));
    return versions;
  }, [wsApi]);
  const fetchFileContentAt = useCallback(async (path, commitHash) => {
    const { content } = await apiGet(wsApi(`/files/content-at/${encodePath(path)}?commit=${commitHash}`));
    return content;
  }, [wsApi]);
  const onOpenCodeCanvas = (file, files) => setCodeCanvas({ open: true, file, files: files || [file] });
  const onUndo = () => guarded(() => apiPost(wsApi('/aider/undo')), 'Undoing last change…');

  // Download flow: clicking Download opens a small rename dialog first; the
  // actual browser download only fires once the user confirms a filename.
  const requestDownload = (path) => setDownloadTarget(path);
  const confirmDownload = (path, chosenName) => {
    const token = localStorage.getItem('aider_token') || '';
    const qs = token ? `?token=${encodeURIComponent(token)}` : '';
    const url = `/api/ws/${encodeURIComponent(currentWorkspace)}/files/download/${path.split('/').map(encodeURIComponent).join('/')}${qs}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = chosenName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setDownloadTarget(null);
    toast(`Downloading ${chosenName}`, 'success');
  };

  const onOpenDiffViewer = (result) => {
    try {
      sessionStorage.setItem('aider_diff_payload', JSON.stringify({
        workspace: currentWorkspace,
        changedFiles: result.changedFiles,
        commits: result.commits,
        diff: result.diff,
        generatedAt: Date.now(),
      }));
      window.open('/diff_viewer_local.html', '_blank');
    } catch (err) {
      toast(`Could not open diff viewer: ${err.message}`, 'error');
    }
  };

  // ------------------------------------------------------------------ command palette shortcut
  useEffect(() => {
    function onKeyDown(e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  // Answering only ever happens through the shared QuestionPrompt now, in
  // both modes, so the plain composer is disabled while one is pending too.
  const busySendDisabled =
    aider.status === 'starting' || aider.status === 'running' || aider.taskRunning || !!aider.pendingQuestion;

  const workspaceBar = (
    <WorkspaceBar
      workspaces={workspaces}
      current={currentWorkspace}
      onSelect={onSelectWorkspace}
      onCreate={onCreateWorkspace}
    />
  );

  if (!currentWorkspace) {
    return (
      <div className="app app-empty">
        <div className="empty-state">
          <div className="brand-mark large">◈</div>
          <h1>Aider Console</h1>
          <p>Create a workspace to get started. Each workspace gets its own folder and its own independent Aider session.</p>
          {workspaceBar}
          <Toasts toasts={toasts} />
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <Sidebar
        workspaceBar={workspaceBar}
        aider={aider}
        models={models}
        ollamaConnected={ollamaConnected}
        workspaceFiles={workspaceFiles}
        attachedFiles={attachedFiles}
        context={contextStats}
        modifiedFiles={modifiedFiles}
        history={history}
        onDownloadFile={requestDownload}
        onUndo={onUndo}
        onStart={onStart}
        onStop={onStop}
        onRestart={onRestart}
        onClear={onClear}
        onTokens={onTokens}
        onModeChange={onModeChange}
        onModelChange={onModelChange}
        onAddFile={onAddFile}
        onDropFile={onDropFile}
        onRefreshFiles={refreshWorkspaceFiles}
        onUpload={onUpload}
      />
      <main className="main">
        <header className="topbar">
          <div className="mode-tabs">
            <button
              className={viewMode === 'terminal' ? 'active' : ''}
              onClick={() => setViewMode('terminal')}
              type="button"
            >
              Terminal
            </button>
            <button
              className={viewMode === 'supervised' ? 'active' : ''}
              onClick={() => setViewMode('supervised')}
              type="button"
            >
              Supervised
            </button>
          </div>
          <div className="topbar-spacer" />
          <div className="workspace-badge mono" title={aider.workspace}>{currentWorkspace}</div>
          <div className="topbar-spacer" />
          <StatusBar
            status={aider.status}
            model={aider.model}
            tokens={tokensSummary}
            ollamaConnected={ollamaConnected}
            ollamaError={ollamaError}
            workspace={aider.workspace}
            onRefreshTokens={onTokens}
            onOpenLibrary={() => setPaletteOpen(true)}
          />
        </header>

        {viewMode === 'terminal' ? (
          <>
            {(aider.status === 'running' || aider.status === 'starting') && (
              <div className="working-banner">
                <span className="spinner" />
                {aider.status === 'starting' ? 'Starting Aider…' : 'Aider is processing your input — generating a response…'}
              </div>
            )}
            <TerminalView onWriteRef={writeRef} initialChunks={rawBufferRef.current} />
            {aider.pendingQuestion && (
              <div className="terminal-question-dock">
                <QuestionPrompt question={aider.pendingQuestion} onAnswer={onAnswerQuestion} />
              </div>
            )}
          </>
        ) : (
          <SupervisedView
            workspaceFiles={workspaceFiles}
            taskRunning={aider.taskRunning}
            transcript={transcript}
            phaseTimeline={phaseTimeline}
            fileProgress={fileProgress}
            elapsedSeconds={elapsedSeconds}
            pendingQuestion={aider.pendingQuestion}
            lastResult={lastTaskResult}
            prefillText={prefillText}
            prefillNonce={prefillNonce}
            onStartTask={onStartTask}
            onStopTask={onStopTask}
            onAnswer={onAnswerQuestion}
            onSwitchToTerminal={() => setViewMode('terminal')}
            onOpenDiffViewer={onOpenDiffViewer}
            onOpenCodeCanvas={onOpenCodeCanvas}
            onFollowUp={onFollowUp}
          />
        )}

        {viewMode === 'terminal' && (
          <Composer
            value={composerText}
            onChange={setComposerText}
            onSend={onSendPrompt}
            disabled={busySendDisabled}
            statusLabel={aider.pendingQuestion ? 'waiting for your answer above' : aider.status}
          />
        )}
      </main>

      <CommandPalette
        open={paletteOpen}
        commands={commands}
        onClose={() => setPaletteOpen(false)}
        onExecute={onExecuteCommand}
        onInsert={onInsertCommand}
      />
      <RenameDownloadModal
        path={downloadTarget}
        onCancel={() => setDownloadTarget(null)}
        onConfirm={confirmDownload}
      />
      <CodeCanvas
        open={codeCanvas.open}
        file={codeCanvas.file}
        files={codeCanvas.files}
        onClose={() => setCodeCanvas({ open: false, file: null, files: [] })}
        fetchVersions={fetchFileVersions}
        fetchContent={fetchFileContentAt}
      />
      <Toasts toasts={toasts} />
    </div>
  );
}
