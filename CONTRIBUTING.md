# Contributing to VibeFlow

Thanks for taking the time to improve VibeFlow.

## Development Setup

```powershell
git clone https://github.com/alperensu/VibeFlow.git
cd VibeFlow
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

On macOS or Linux:

```bash
git clone https://github.com/alperensu/VibeFlow.git
cd VibeFlow
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Checks

Run tests before opening a pull request:

```bash
python -m pytest
```

Run the CLI doctor:

```bash
vibeflow doctor --json
```

## Contribution Guidelines

- Keep the sidecar editor-agnostic. Editor integrations should call the API or CLI.
- Prefer AST and structured parsing over regex for supported languages.
- Preserve the token-savings report in `/context` responses when changing context assembly.
- Keep runtime artifacts out of commits: `.venv/`, `.vibeflow/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/`.
- Do not commit agent-specific instruction files by default. Use `vibeflow agent init <agent>` to generate one locally.

## Good First Areas

- More tree-sitter extractors for JavaScript and TypeScript.
- Better import resolution for cross-file call graphs.
- Optional high-quality embedding providers.
- More benchmark fixtures for token and latency measurements.
