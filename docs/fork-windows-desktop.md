# Windows tray and console

The Windows executable starts in the notification area without opening a terminal.
Its tray icon is the same icon embedded in `flaresolverr.exe`.

- **Single left-click:** show or hide the built-in FlareSolverr console.
- **View console:** show the current session's log. Logging continues while the window is hidden;
  closing the window hides it and leaves FlareSolverr running.
- **Edit configuration:** open the built-in JSON editor. Configuration is stored in
  `%APPDATA%\FlareSolverr\config.json`; saved changes take effect after restarting.
  The settings use the environment variable names documented below. Existing environment
  variables take priority. Relative `LOG_FILE` paths are relative to the configuration file.
- **Log to disk:** enable or disable file logging immediately and remember the choice.
  The default destination is `%APPDATA%\FlareSolverr\logs\flaresolverr.log`.
  Files rotate at 5 MiB with three backups. Set `LOG_FILE` to choose another destination.
- **Exit:** stop the API server and remove the tray icon.

The console is a native application window, not a terminal or browser. Its session log
is kept in memory until FlareSolverr exits. Disk logging is optional and off by default.

Service deployments remain supported: start `flaresolverr.exe --no-tray` with your existing
service manager and environment variables. Windows session-zero services automatically
skip the desktop interface. Use `LOG_FILE` for service logs, or pass `--config <path>` to
load a JSON configuration. Running from source keeps the existing foreground behavior;
`python src/fork_windows_launcher.py` enables the Windows desktop interface explicitly.


## Upstream updates

The desktop launcher is maintained in the separate `src/fork_windows/` namespace. The custom Windows
build first runs the original upstream build script, then places its entire output
unchanged in `core/` and adds the tray launcher at the package root. The upstream
entry point, browser code, dependencies, build script, and README remain unchanged.
Upstream sync and the existing custom build workflow apply this automatically.
Linux packages continue to use the upstream build directly.
