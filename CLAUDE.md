# Notes for coding agents

Read CONTRIBUTING.md first - its rules apply to every change, yours too.
The ones most easily missed:

- **No file access on Home Assistant's event loop** (CONTRIBUTING.md "Home
  Assistant's rules"). In `async def` and `@callback` code: no `open`,
  `read_*`, `write_*`, `exists`, `is_dir`, `glob`, `stat`, `mkdir`... -
  put it in a plain function run with `hass.async_add_executor_job`, or use
  HA's `Store`. Don't hold big files (theme packs) in memory - read them
  when asked. `tests/test_event_loop_io.py` fails otherwise; never silence
  it with `# (not a file)` on real file access.
- **Only Room Tiles' own secrets**; services that touch files admin-only and
  inside `room_tiles_backups/`.
- **MIRRORED** logic changes on both sides (panel firmware and dashboard).
- User-facing text from the wording files, US English, short and friendly.
- Docs and commit messages are public: describe how things work now - no
  personal details.
- Run the checks before calling a change done: `pytest`; in `frontend/`
  `npm run typecheck` and `npm test`.
