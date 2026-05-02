# VibeFlow

VibeFlow is a local, editor-agnostic context optimization sidecar for AI coding workflows. It runs as a FastAPI server on your machine, watches a project, builds a compact AST-aware memory of the codebase, and returns model-ready context that avoids sending the whole repository to an assistant.

The goal is simple: give coding agents the right context, in the right shape, with less latency and fewer tokens.

## What It Does

- Watches project files with `watchdog` and keeps an incremental index warm.
- Parses Python source with `tree-sitter` instead of relying on plain text search.
- Skeletonizes large files into imports, class headers, and function signatures.
- Keeps a local vector cache with ChromaDB, with an in-memory fallback for development.
- Prunes unrelated files semantically before building context.
- Separates static project context from dynamic task context for prompt caching.
- Constrains downstream model output to unified git diff format.
- Falls back to smart chunking with a clear `nonsense` warning when AST parsing is unsafe.

## Architecture

```text
Editor / Agent
    |
    | POST /context
    v
FastAPI Local Server
    |
    +-- Watcher Engine        -> incremental file updates
    +-- AST-Based Sieve       -> tree-sitter signatures, types, calls
    +-- Skeletonizer          -> compact static project context
    +-- Vector Cache          -> semantic pruning with ChromaDB
    +-- Context Builder       -> cache-friendly prompt package
    +-- Diff Contract         -> git diff output instruction
```

## Project Layout

```text
api/        FastAPI routes and server lifecycle
core/       AST sieve, skeletonizer, watcher, indexer, context builder
storage/    vector cache adapter
scripts/    Windows startup task helpers
tests/      focused unit tests
run.py      server entry point
```

## Quick Start

From the project you want VibeFlow to watch:

```powershell
C:\Users\alper\Desktop\VibeFlow\vibeflow.ps1
```

Or from CMD:

```cmd
C:\Users\alper\Desktop\VibeFlow\vibeflow.cmd
```

That single command:

1. Finds Python.
2. Creates `.venv` if it does not exist.
3. Installs `requirements.txt`.
4. Starts the local API at `http://127.0.0.1:7400`.
5. Indexes the current directory.
6. Starts the file watcher.

To watch a specific project:

```powershell
C:\Users\alper\Desktop\VibeFlow\vibeflow.ps1 -ProjectRoot "C:\path\to\project"
```

## Manual Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py --port 7400 --project-root "C:/path/to/project"
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:7400/health
```

## Windows Auto Start

Install VibeFlow as a Windows logon task:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows-task.ps1 -ProjectRoot "C:\path\to\project"
```

Remove the startup task:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\remove-windows-task.ps1
```

## API

### Inspect Optimization Settings

```http
GET /settings/options
```

This returns the available profiles, every user-facing optimization switch, and the expected token/latency trade-off for each one.

Built-in profiles:

- `maximum_savings`: smallest prompt footprint, strict file/symbol budgets.
- `balanced`: more context while keeping pruning and caching enabled.
- `quality`: wider retrieval budgets for harder refactors.
- `debug_fuller`: disables the main savings path so you can inspect fuller context.

### Index a Project

```http
POST /index
Content-Type: application/json

{
  "project_root": "C:/path/to/project",
  "watch": true
}
```

### Build Optimized Context

```http
POST /context
Content-Type: application/json

{
  "project_root": "C:/path/to/project",
  "current_file": "src/app.py",
  "cursor_line": 42,
  "intent": "Refactor validation flow",
  "profile": "maximum_savings",
  "settings": {
    "semantic_pruning": true,
    "function_level_retrieval": true,
    "include_cross_file_callees": true,
    "prompt_caching": true,
    "diff_only_output": true,
    "max_files": 6,
    "max_symbols": 12
  }
}
```

Response shape:

```json
{
  "context_string": "...",
  "prompt": {
    "headers": {
      "anthropic-beta": "prompt-caching",
      "content-type": "application/json"
    },
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "name": "static_project_context",
            "cache_control": { "type": "ephemeral" },
            "text": "..."
          },
          {
            "type": "text",
            "name": "dynamic_task_context",
            "text": "..."
          }
        ]
      }
    ],
    "response_contract": {
      "format": "git_diff",
      "instruction": "Return changes only as a unified git diff..."
    }
  },
  "stats": {
    "latency_ms": 12.4,
    "files_selected": 8,
    "symbols_selected": 12,
    "estimated_total_token_saving_percent": 91.3,
    "optimization_effects": [
      {
        "key": "semantic_pruning",
        "enabled": true,
        "estimated_saved_tokens": 42000,
        "basis": "project raw tokens minus selected raw file tokens"
      },
      {
        "key": "prompt_caching",
        "enabled": true,
        "estimated_cacheable_tokens": 3200,
        "basis": "static context tokens eligible for provider prompt caching"
      }
    ]
  },
  "warnings": []
}
```

### Extract Python Signatures

```http
POST /sieve/signatures
Content-Type: application/json

{
  "file_path": "C:/path/to/project/src/app.py",
  "language": "python"
}
```

This returns imports, class skeletons, top-level function signatures, parse warnings, and the full file skeleton.

## Token Optimization Strategy

VibeFlow reduces context size with a layered pipeline:

1. **Skeletonization** keeps structural code shape while removing implementation bodies.
2. **Semantic pruning** selects only relevant files from the local vector cache.
3. **Function-level retrieval** indexes functions/classes separately so matched symbols can be supplied without whole files.
4. **Cross-file callee expansion** resolves directly called symbols by name and includes only those bodies.
5. **Active body extraction** includes the function at the cursor plus directly called local functions.
6. **Prompt caching layout** separates stable project context from per-task dynamic context.
7. **Diff-only output** prevents full-file restatement after context has already been supplied.

Each `/context` response includes `stats.optimization_effects`, so clients can show users which settings saved prompt tokens, which settings add context for quality, and how many static tokens are cacheable.

## Development

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Start a development server:

```powershell
.\.venv\Scripts\python.exe run.py --reload --project-root .
```

## Current Scope

The first production path is optimized for Python:

- Python AST parsing with `tree-sitter-python`
- function and method signature extraction
- class/type skeleton extraction
- direct call detection inside Python functions

JavaScript and TypeScript are listed in configuration for future extractor support, but Python is the implemented sieve path today.

## License

MIT License. See [LICENSE](LICENSE).
