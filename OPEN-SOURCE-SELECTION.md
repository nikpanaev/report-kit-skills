# Source capability selection — offline preparation

| Capability | Source / exact identity | License / distribution | Decision |
|---|---|---|---|
| LiveDune transport | Ready mcp-openapi0.3.0, original spec1.0.10 hash in recipe | Backend declares MIT in actual installed metadata; binary/node_modules not shipped; transitive license review pending | Reuse; preserve GET guard/raw archive/cap, no own HTTP client |
| Browser automation | Existing Playwright1.63.0 | Actual installed Playwright1.63.0 metadata: Apache-2.0, Python>=3.10; runtime/browser not shipped; complete distribution notices review pending | Reuse approved version, no new engine |
| Source capture/session/zoom/FIFO | Owner-maintained exported code, SOURCE-PROVENANCE.json | Owner distribution license pending; no historical private evidence/author metadata | Adapt only portable paths/privacy and synthetic fixtures |
| Persistence/path validation | Python SQLite/pathlib and Node fs/path | Standard library, no third-party dependency added | One external private store; scoped local checks |
| Secret storage | Existing macOS Keychain adapter | No key/cookie/session shipped; other OS mechanism not selected | Keep bounded adapter; not portable secret-store success |
| Installation/update | Native host plugin mechanism | No hook/server/global config changes in this slice | Prepare source manifests; actual device install deferred |

Canonical references: https://registry.npmjs.org/mcp-openapi/0.3.0 ; https://github.com/Docat0209/mcp-openapi ; https://api.livedune.com/docs/openapi.json . Recipe and lock provide identities, not permission to download or execute. Source cache is not a new verified installation.

No standalone runtime, package manager wrapper, browser launcher or API bridge is implemented. Missing capabilities stop the relevant source step. Complete license/supply-chain review and independent security remain release requirements.

## Current dependency observation

[Metadata inventory](dependencies/REVIEW.json) covers134 npm exact versions and four observed Python distributions. [Findings/limits](THIRD-PARTY-DEPENDENCIES.md): effective Node>=20 for frozen LiveDune chain; Python transitive resolver not frozen; esbuild postinstall needs approved runtime validation. Source origins18/18 across the two packages match their recorded hashes. These results do not close ownership/license/security/host acceptance. No dependency installed, version changed or third-party code vendored.
