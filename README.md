# Agentic Workbench CLI

**Version:** 2.1.0  
**Package:** `agentic-workbench-cli`  
**Description:** Agentic Workbench v2 — Developer Productivity Framework for Multi-Agent Systems

## Overview

The Workbench CLI (`workbench-cli.py`) is the deterministic bootstrapper for the Agentic Workbench v2. It initializes new application repositories with the workbench scaffold and handles engine upgrades.

## Commands

```
workbench-cli.py init <project-name>     Initialize new application repo with workbench scaffold
workbench-cli.py upgrade --version <vX.Y> Upgrade existing repo to new workbench version
workbench-cli.py status                  Display state.json in human-readable format
workbench-cli.py rotate                  Trigger memory_rotator.py for sprint end
```

## Installation

The CLI is installed globally via pip or cloned from the template repository:

```bash
pip install agentic-workbench-cli
```

## See Also

- [Agentic Workbench v2 - Draft.md](../Agentic%20Workbench%20v2%20-%20Draft.md) — Full specification
- [Beginners_Guide.md](../docs/Beginners_Guide.md) — Usage guide