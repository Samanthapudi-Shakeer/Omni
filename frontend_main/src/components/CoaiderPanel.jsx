import CoaiderConsole from '../coaider/App'
import '../coaider/styles.css'

// This is the original, complete Aider Console embedded as one of the main
// features. App.jsx owns the workspace selection and passes it to Coaider,
// so its file operations and every other feature tab use the same folder.
export default function CoaiderPanel({ workspaces, workspace, setWorkspace, createWorkspace }) {
  return <div className="coaider-console-shell">
    <CoaiderConsole
      workspaces={workspaces}
      currentWorkspace={workspace}
      onSelectWorkspace={setWorkspace}
      onCreateWorkspace={createWorkspace}
    />
  </div>
}
