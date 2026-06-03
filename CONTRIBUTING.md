# Contributing

Thanks for your interest in improving this project.

## Before you contribute

- This project targets Windows desktop usage.
- Keep the app visible and user-controllable.
- Do not add hidden monitoring, stealth startup, privilege bypass, or keylogging behavior.

## Development setup

1. Install Python 3.11+
2. Install dependencies:

```powershell
cd .\outputs\who_touched_my_pc
pip install -r requirements.txt
```

3. Run locally:

```powershell
.\run.ps1
```

## Preferred contribution scope

- UI polish
- Stability fixes
- Better error handling
- Packaging improvements
- Documentation improvements
- Safer configuration and export flow

## Pull request notes

- Keep changes focused
- Explain user-visible impact clearly
- Do not commit `config.json`, logs, screenshots, photos, or packaged `.exe` files
- Prefer changes that preserve the visible and authorized-use design of the project

## Reporting issues

When opening an issue, include:

- Windows version
- App version
- Steps to reproduce
- Expected behavior
- Actual behavior
- Screenshots or logs if available

