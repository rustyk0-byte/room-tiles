# Contributing to Room Tiles

Bug fixes, features, translations and support for more devices are welcome.
Every change goes through a pull request, and the maintainer reviews and
approves it before it's merged.

Room Tiles is under the Apache License 2.0 ([LICENSE](LICENSE)); what you
contribute is under the same license.

## How

1. **Fork** this repository and create a branch for your change.
2. Make the change, with tests where it changes behavior.
3. Open a **pull request** against `main`. The checks run automatically
   (for a first-time contributor, once the maintainer lets them start).
4. The maintainer reviews it. Changes may be asked for; push them to the same
   branch. Once it's approved, the maintainer merges it, and it goes out with
   the next release.

For something big, open an issue first so we can agree on the approach
before you put the work in.

## Running the checks yourself

- **Integration (Python):** `pip install -r requirements_test.txt`, then
  `pytest`.
- **Dashboard:** in `frontend/`: `npm install`, `npm run typecheck`,
  `npm test`.
- **Panel firmware:** `tools/sync-firmware.sh build`, then in `build/`:
  `esphome compile room-tiles-<board>.yaml` (ESPHome version: see
  `.github/workflows/firmware.yml`).

## Guidelines

- **Text:** everything the user reads comes from the wording files
  (`frontend/i18n/<language>.json`, English the full set). Short and
  friendly, in US English. If you can, add your text in the other languages
  too - or leave English there and say so in the pull request.
- **Panels and dashboard behave alike:** logic that exists on both sides is
  marked `MIRRORED` in both places; change both.
- **Privacy:** no personal details in code, tests, screenshots or commit
  messages - no names, addresses, serial numbers or entity ids from your
  home.
- **Docs:** keep the README and docs/ describing how things work now.
