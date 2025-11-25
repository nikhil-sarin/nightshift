# NightShift Sandboxing System

## Overview

NightShift implements filesystem sandboxing on macOS using the native `sandbox-exec` utility. This provides an additional security layer by restricting the executor agent's ability to write files to only explicitly approved directories.

**Key Benefits:**
- **Defense in depth**: Even if Claude misbehaves or is compromised, filesystem writes are restricted
- **Principle of least privilege**: Tasks only get write access to directories they actually need
- **Audit trail**: Sandbox violations are logged, making unauthorized access attempts visible

## How It Works

### 1. Task Planning Phase

When you submit a task via `nightshift submit`, the Task Planner agent analyzes the request and determines which directories need write access:

```python
# In task_planner.py
plan = {
    "enhanced_prompt": "...",
    "allowed_tools": ["Read", "Write", "Bash"],
    "allowed_directories": ["/absolute/path/to/project"],  # ← Sandbox permissions
    "system_prompt": "...",
    ...
}
```

**Planning Logic:**
- Analyzes the user's task description for file output requirements
- Defaults to current working directory for unspecified tasks
- Uses absolute paths only (relative paths are resolved during planning)
- Explicitly lists each directory that needs write access
- Never grants write access to system directories (`/`, `/usr`, `/System`, etc.)

### 2. Sandbox Profile Generation

The `SandboxManager` (in `nightshift/core/sandbox.py`) generates a macOS sandbox profile (`.sb` file) that:

1. **Denies all operations by default**
2. **Explicitly allows** specific operations:
   - Read access to all files (`file-read*`)
   - Process execution and forking (`process-exec*`, `process-fork`)
   - Network access (`network*`)
   - IPC for subprocess communication (`ipc*`, `mach*`)
3. **Selectively allows writes** to:
   - Directories specified in `allowed_directories`
   - System temp directories (`/tmp`, `/private/tmp`, `/var/tmp`)
   - Claude CLI config files (`~/.claude.json`, `~/.claude/`)
   - MCP tool credentials (e.g., `~/.google_calendar_token.json`)

**Example generated profile:**

```scheme
(version 1)

;; Deny everything by default
(deny default)

;; Allow process execution and basic operations
(allow process-exec*)
(allow process-fork)
(allow signal)
(allow sysctl-read)

;; Allow reading all files
(allow file-read*)

;; Allow network access
(allow network*)

;; Allow IPC for subprocess communication
(allow ipc*)
(allow mach*)

;; Allow writes to specific files
(allow file-write* (literal "/Users/james/.claude.json"))
(allow file-write* (literal "/Users/james/.google_calendar_token.json"))

;; Allow writes to specified directories
(allow file-write* (subpath "/Users/james/projects/myproject"))
(allow file-write* (subpath "/tmp"))
```

### 3. Sandboxed Execution

When the executor runs, the Claude CLI command is wrapped with `sandbox-exec`:

```bash
sandbox-exec -f /tmp/nightshift_sandbox_XXXXX.sb claude -p "..." --output-format stream-json
```

**What happens during execution:**
- The Claude process runs inside the sandbox
- Any attempt to write outside allowed directories is **blocked by the kernel**
- MCP tools (Write, Bash, etc.) can only create/modify files in approved locations
- Sandbox violations are logged as errors

### 4. Validation and Safety Checks

Before sandboxing, `SandboxManager.validate_directories()` rejects dangerous paths:

```python
# These will raise ValueError
dangerous_paths = [
    "/", "/private",
    "/etc", "/private/etc",
    "/var", "/private/var",
    "/bin", "/usr", "/sbin",
    "/System", "/Library",
    "/Applications", "/Volumes"
]
```

Additional safety measures:
- Warns if entire home directory is allowed (suggests using subdirectories)
- Resolves symlinks to prevent directory traversal bypasses
- Validates that allowed directories exist before execution

## Using the Sandbox System

### Automatic Directory Detection (Recommended)

Let the Task Planner automatically determine required directories:

```bash
nightshift submit "Analyze data.csv and save results to output.txt"
```

The planner will grant write access to the current directory since the task writes locally.

### Manual Directory Specification

Override or extend the planner's suggestions:

```bash
nightshift submit "Build documentation" --allow-dir /path/to/docs
nightshift submit "Update repos" --allow-dir ~/project1 --allow-dir ~/project2
```

You can specify `--allow-dir` multiple times for tasks that write to multiple locations.

### Checking Sandbox Configuration

Use `--debug` to inspect the sandbox profile before execution:

```bash
nightshift submit "task description" --debug
```

This displays:
- Full `sandbox-exec` command
- Path to the `.sb` profile file
- List of allowed directories

### Disabling Sandboxing

Sandboxing is enabled by default on macOS. To disable (not recommended):

```python
# In code
agent_manager = AgentManager(
    task_queue,
    logger,
    enable_sandbox=False  # ← Disable sandboxing
)
```

**Note:** Sandboxing is automatically disabled on non-macOS systems where `sandbox-exec` is unavailable.

## Troubleshooting

### "Operation not permitted" Errors

**Symptom:** Claude reports file write failures or bash commands fail with permission errors.

**Cause:** The task tried to write to a directory not in `allowed_directories`.

**Solution:**
1. Check the task plan: `nightshift queue --status staged`
2. Look at the "Allowed Directories" field
3. Re-submit with `--allow-dir` to grant additional permissions:
   ```bash
   nightshift submit "same task" --allow-dir /path/to/needed/directory
   ```

### "Sandbox validation failed" Errors

**Symptom:** Task fails immediately with "Refusing to allow writes to system directory".

**Cause:** The Task Planner or user specified a dangerous system directory.

**Solution:**
1. Never request write access to `/`, `/usr`, `/System`, etc.
2. Use a subdirectory in your home directory instead:
   ```bash
   nightshift submit "task" --allow-dir ~/workspace/output
   ```

### Sandbox Profile Not Found

**Symptom:** Error message about missing `.sb` file.

**Cause:** The temporary sandbox profile was deleted prematurely.

**Solution:** This should not happen in normal operation. If it does, restart the task. Check that `/tmp` is writable.

### GitHub CLI (gh) Authentication Fails in Sandbox

**Symptom:** `gh` commands report "invalid token" or authentication errors, even though `gh auth status` works outside the sandbox.

**Cause:** macOS sandbox blocks access to the Keychain where gh stores authentication tokens.

**Solutions:**

Option 1: Use a token file (recommended):
```bash
# Get your current token
gh auth token

# Create a token file in gh config
echo "your_token_here" > ~/.config/gh/token.txt

# Configure gh to use the token file
export GH_TOKEN=$(cat ~/.config/gh/token.txt)
```

Option 2: Store token in hosts.yml instead of keychain:
```bash
# Log out and re-authenticate with file-based storage
gh auth logout
gh auth login --with-token < ~/.config/gh/token.txt
```

Option 3: Use the `GH_TOKEN` environment variable (for specific tasks):
```bash
export GH_TOKEN="your_token_here"
nightshift submit "create a gh issue..." --auto-approve
```

The sandbox already allows read/write access to `~/.config/gh/` when `needs_git=true`, so file-based token storage will work.

### Task Works Without Sandbox but Fails With Sandbox

**Symptom:** Task succeeds when sandboxing is disabled but fails when enabled.

**Cause:** Task is attempting undeclared filesystem writes.

**Solution:**
1. Examine the full output: `nightshift results task_XXXXX --show-output`
2. Identify which file/directory caused the permission error
3. Re-submit with that directory included in `--allow-dir`
4. Consider if the task should really need that access (security review)

### MCP Tool Credential Errors

**Symptom:** Google Calendar or other MCP tools fail with "Permission denied" when updating tokens.

**Cause:** The MCP tool needs to refresh OAuth tokens stored in home directory.

**Solution:** This should be handled automatically. If it persists, verify that these files are writable:
- `~/.google_calendar_token.json`
- `~/.google_calendar_credentials.json`

Check `sandbox.py` line 61-65 to ensure credential files are in the `allowed_files` list.

## Architecture Details

### Component Responsibilities

| Component | File | Responsibility |
|-----------|------|----------------|
| **TaskPlanner** | `task_planner.py` | Analyzes tasks, determines required directories |
| **SandboxManager** | `sandbox.py` | Generates `.sb` profiles, wraps commands with `sandbox-exec` |
| **AgentManager** | `agent_manager.py` | Orchestrates sandboxed execution, handles validation |
| **Task** | `task_queue.py` | Stores `allowed_directories` in database |

### Execution Flow

```
1. User submits task
   ↓
2. TaskPlanner.plan_task() determines allowed_directories
   ↓
3. Task stored in database (STAGED state)
   ↓
4. User approves (or --auto-approve)
   ↓
5. AgentManager._build_command() calls SandboxManager.wrap_command()
   ↓
6. SandboxManager.create_profile() generates .sb file
   ↓
7. Command wrapped: sandbox-exec -f profile.sb claude -p "..."
   ↓
8. Executor runs in sandbox, writes restricted to allowed_directories
   ↓
9. SandboxManager.cleanup() deletes temporary .sb file
```

### Database Schema

The `allowed_directories` field is stored as JSON in the `tasks` table:

```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    allowed_tools TEXT,        -- JSON array
    allowed_directories TEXT,  -- JSON array ← Sandbox permissions
    system_prompt TEXT,
    ...
);
```

### Future Enhancements

Potential improvements to the sandboxing system:

- **Network isolation**: Restrict network access to specific domains (requires TCC/MDM on modern macOS)
- **Read restrictions**: Limit read access to specific directories (currently all files are readable)
- **Process limits**: Restrict child process spawning or CPU/memory usage
- **Audit logging**: Log all sandbox violations to a dedicated file for security review
- **Profile caching**: Reuse profiles for tasks with identical directory requirements

## References

- [macOS Sandbox Guide](https://reverse.put.as/wp-content/uploads/2011/09/Apple-Sandbox-Guide-v1.0.pdf)
- [sandbox-exec man page](https://www.unix.com/man-page/osx/8/sandbox-exec/)
- NightShift Architecture: See `CLAUDE.md` for system overview
