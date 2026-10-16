"""Fork-owned Windows launcher. Upstream flaresolverr.py remains untouched."""
import argparse
import ctypes
from ctypes import wintypes
import multiprocessing
import os
import subprocess
import sys

from fork_windows.runtime import DesktopSettings
from fork_windows.process import core_command, run_core


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description='FlareSolverr for Windows')
    parser.add_argument('--no-tray', action='store_true', help='Run without the desktop interface (services).')
    parser.add_argument('--config', help='JSON configuration file path.')
    options = parser.parse_args()
    settings = DesktopSettings(options.config)
    session = wintypes.DWORD()
    interactive = ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)) and session.value != 0
    if interactive and not options.no_tray:
        from fork_windows.desktop import DesktopApp
        DesktopApp(settings, run_core).run()
        return 0

    # Preserve environment-only service deployments, unless a config is requested.
    if options.config:
        settings.load()
        settings.apply_environment()
    from fork_windows.tray import keep_browser_children_with_app
    job = keep_browser_children_with_app()  # Kept open until this process exits.
    return subprocess.call(core_command(), stdin=subprocess.DEVNULL,
                           stdout=None if sys.stdout is not None else subprocess.DEVNULL,
                           stderr=None if sys.stderr is not None else subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW)


if __name__ == '__main__':
    sys.exit(main())
