# Deletion and deprecation register

No runtime data, database, recordings, logs, release packages, resource assets,
`node_modules`, `__pycache__` or `temp_clone` was deleted in Stage 5.

| Item | Decision | Evidence/next action |
|---|---|---|
| old `app.py`/Socket imports | retain compatibility | remove only after one release and external import audit |
| old ambient singleton routes | retain | replace only after multi-device broker acceptance |
| `MappingResolver/course_map` | retain as fallback | remove only after historical course/session regression |
| `child_media_agent` | retain shim | Runtime and external deployment audit first |
| old docs | superseded, archived copies | canonical docs at root `docs/`; links must be repaired before deletion |
| generated caches/logs | candidate only | clean in a separate approved release operation, never during audit |

Every future deletion needs a reference/runtime/config/package search, a
deprecated shim and warning period, a rollback location and an explicit user
approval when a delivery asset is involved.
