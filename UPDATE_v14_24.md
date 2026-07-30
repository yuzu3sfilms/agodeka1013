# v14.24 Project AGO Identity Foundation

## Changes

- Renamed the project identity to **Project AGO**.
- Defined AGO as **Alternative Generated Organism**.
- Named the first deployed personality instance **AGO-HASHIMOTO**.
- Added `project_identity.py` as the single source of truth for project name, instance and version.
- Updated runtime logs, root endpoint and health endpoint to report Project AGO metadata.
- Renamed the main class to `AgoHashimotoBot` while preserving `HashimotoArataBot` as a compatibility alias.
- Replaced the outdated README with a current architecture and deployment guide.
- Preserved the v14.23 persona compiler and unified behavior policy without changing replay safety gates.
