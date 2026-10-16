"""Wrap the unchanged upstream Windows package with the fork's desktop launcher."""
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[2]
    package = root / 'dist' / 'package' / 'flaresolverr'
    already_wrapped = (package / 'core' / 'flaresolverr.exe').is_file()
    if not already_wrapped and not (package / 'flaresolverr.exe').is_file():
        raise FileNotFoundError('Build the upstream Windows package before adding the desktop launcher.')
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
        '--name', 'flaresolverr', '--icon', str(root / 'resources' / 'flaresolverr_logo.ico'),
        '--add-data', f'{root / "resources" / "flaresolverr_logo.ico"};resources',
        '--distpath', str(root / 'dist' / 'desktop'),
        '--workpath', str(root / 'build' / 'desktop'),
        '--specpath', str(root / 'build' / 'desktop'),
        str(root / 'src' / 'fork_windows_launcher.py'),
    ], cwd=root, check=True)
    # Move the entire upstream layout intact; none of its files are replaced.
    if not already_wrapped:
        staging = package.with_name('upstream-core')
        package.replace(staging)
        package.mkdir()
        staging.replace(package / 'core')
    shutil.copy2(root / 'dist' / 'desktop' / 'flaresolverr.exe', package / 'flaresolverr.exe')
    shutil.make_archive(str(root / 'dist' / 'flaresolverr_windows_x64'), 'zip', root / 'dist' / 'package')


if __name__ == '__main__':
    main()
