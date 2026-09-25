"""
Reference metadata for Aider's built-in slash commands, used to power the
command palette and an in-app "what does this do" library. This is
documentation only -- every entry, when invoked, still sends the exact same
command text into the real Aider PTY. Nothing here reimplements behavior.
"""

COMMANDS = [
    {"cmd": "/add", "args": "<file>", "desc": "Add a file to the chat so Aider can see and edit it.", "immediate": False},
    {"cmd": "/drop", "args": "<file>", "desc": "Remove a file from the chat context.", "immediate": False},
    {"cmd": "/clear", "args": "", "desc": "Clear the chat history (keeps attached files).", "immediate": True},
    {"cmd": "/reset", "args": "", "desc": "Drop all files and clear the chat history.", "immediate": True},
    {"cmd": "/tokens", "args": "", "desc": "Show token usage: how much of the model's context window is used vs remaining.", "immediate": True},
    {"cmd": "/diff", "args": "", "desc": "Show the diff of changes made since the last message.", "immediate": True},
    {"cmd": "/undo", "args": "", "desc": "Undo Aider's last commit, if it was made by Aider.", "immediate": True},
    {"cmd": "/commit", "args": "[message]", "desc": "Commit outstanding changes to the repo, optionally with a custom message.", "immediate": True},
    {"cmd": "/run", "args": "<command>", "desc": "Run a shell command and optionally share the output with Aider.", "immediate": False},
    {"cmd": "/test", "args": "<command>", "desc": "Run a test command; failures are automatically shared with Aider for fixing.", "immediate": False},
    {"cmd": "/lint", "args": "[file]", "desc": "Lint files that have been edited, or a specific file.", "immediate": True},
    {"cmd": "/map", "args": "", "desc": "Show Aider's repository map (the high-level structure it uses for context).", "immediate": True},
    {"cmd": "/map-refresh", "args": "", "desc": "Force a refresh of the repository map.", "immediate": True},
    {"cmd": "/ask", "args": "<question>", "desc": "Ask a question about the code without making any edits (one-off ask, regardless of current mode).", "immediate": False},
    {"cmd": "/code", "args": "<instruction>", "desc": "Request a code change (one-off code edit, regardless of current mode).", "immediate": False},
    {"cmd": "/architect", "args": "<instruction>", "desc": "Discuss/plan an approach at a higher level before code is written (one-off, regardless of current mode).", "immediate": False},
    {"cmd": "/chat-mode", "args": "<ask|code|architect>", "desc": "Switch the session's persistent chat mode.", "immediate": False},
    {"cmd": "/model", "args": "<name>", "desc": "Switch the active model for this session.", "immediate": False},
    {"cmd": "/read-only", "args": "<file>", "desc": "Add a file as read-only context (Aider can see it but won't edit it).", "immediate": False},
    {"cmd": "/save", "args": "<name>", "desc": "Save the current chat/session state to a named file for later reload.", "immediate": False},
    {"cmd": "/load", "args": "<name>", "desc": "Load a previously saved chat/session state.", "immediate": False},
    {"cmd": "/copy", "args": "", "desc": "Copy the last Aider response to the clipboard.", "immediate": True},
    {"cmd": "/copy-context", "args": "", "desc": "Copy the current chat context (files + history) to the clipboard.", "immediate": True},
    {"cmd": "/web", "args": "<url>", "desc": "Fetch a URL's content and add it to the chat as context.", "immediate": False},
    {"cmd": "/voice", "args": "", "desc": "Record a voice message as your next input (requires mic support in the actual terminal).", "immediate": True},
    {"cmd": "/help", "args": "[question]", "desc": "Ask Aider how to use Aider itself.", "immediate": False},
    {"cmd": "/ls", "args": "", "desc": "List all files in the current chat/repo that Aider is tracking.", "immediate": True},
    {"cmd": "/git", "args": "<command>", "desc": "Run a raw git command against the workspace repo.", "immediate": False},
    {"cmd": "/exit", "args": "", "desc": "Exit the Aider session (use Stop in this UI instead, to keep the process managed cleanly).", "immediate": False},
]
