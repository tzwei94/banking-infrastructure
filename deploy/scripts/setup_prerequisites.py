"""macOS workstation checks and explicitly selected installations (no AWS calls)."""
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import tempfile


def probe(args):
    try:
        result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=30)
        return result.returncode == 0, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def activate_tools():
    """Expose keg-only tools to this menu and its children; never edit shell files."""
    if platform.system() != 'Darwin':
        return
    prefix = Path('/opt/homebrew' if platform.machine() == 'arm64' else '/usr/local')
    java = prefix / 'opt/openjdk@25/libexec/openjdk.jdk/Contents/Home'
    paths = [prefix / 'opt/node@24/bin', prefix / 'opt/openssl@3/bin',
             prefix / 'bin', prefix / 'sbin']
    if (java / 'bin/java').exists():
        os.environ['JAVA_HOME'] = str(java)
        paths.insert(0, java / 'bin')
    existing = os.environ.get('PATH', '').split(os.pathsep)
    selected = [str(p) for p in paths if p.is_dir()]
    os.environ['PATH'] = os.pathsep.join(dict.fromkeys(selected + existing))


CHECKS = [
    ('Apple command line tools', ['xcode-select', '-p'], None),
    ('Homebrew', ['brew', '--version'], None),
    ('uv', ['uv', '--version'], None),
    ('Git', ['git', '--version'], None),
    ('Make', ['make', '--version'], None),
    ('Bash', ['bash', '--version'], None),
    ('curl', ['curl', '--version'], None),
    ('unzip', ['unzip', '-v'], None),
    ('OpenSSL', ['openssl', 'version'], None),
    ('jq', ['jq', '--version'], None),
    ('AWS CLI v2', ['aws', '--version'], r'aws-cli/2\.'),
    ('Terraform >=1.10, <2', ['terraform', 'version'], r'Terraform v1\.(?:1[0-9]|[2-9][0-9]|[1-9][0-9]{2,})\.'),
    ('GitHub CLI', ['gh', '--version'], None),
    ('Session Manager plugin', ['session-manager-plugin', '--version'], None),
    ('Java 25 (local verify)', ['java', '-version'], r'version "25[.\"]'),
    ('Node 24 (local verify)', ['node', '--version'], r'^v24\.'),
    ('Docker engine', ['docker', 'info', '--format', '{{.ServerVersion}}'], None),
    ('Docker Compose', ['docker', 'compose', 'version'], None),
    ('Docker Buildx', ['docker', 'buildx', 'version'], None),
]


def check():
    activate_tools()
    failed = []
    for label, command, pattern in CHECKS:
        ok, output = probe(command)
        ok = ok and (pattern is None or re.search(pattern, output) is not None)
        print(f"{'OK' if ok else 'NEEDS ATTENTION':15} {label}: {output.splitlines()[0] if output else 'no output'}")
        if not ok:
            failed.append(label)
    print('Python for this menu is managed by uv; Maven uses app/mvnw. No separate Maven installation is needed.')
    return failed


def execute(commands, confirm=True):
    for command in commands:
        print('$ ' + shlex.join(command))
    if confirm and input('Run these commands on this Mac? Type yes: ').strip() != 'yes':
        return False
    for command in commands:
        subprocess.run(command, check=True)
    activate_tools()
    return True


def install(packages, cask=False):
    brew = shutil.which('brew')
    if not brew:
        raise ValueError('Install Homebrew first through Install all prerequisites, then retry.')
    execute([[brew, 'install', *(['--cask'] if cask else []), *packages]])


def docker():
    for name in ('OrbStack', 'Docker'):
        if any((base / f'{name}.app').exists() for base in (Path('/Applications'), Path.home() / 'Applications')):
            execute([['open', '-a', name]])
            print('Finish any app setup and wait for Docker to start, then run the checks again.')
            return
    choice = input('Docker runtime: 1 OrbStack, 2 Docker Desktop, 0 back: ').strip()
    if choice in {'1', '2'}:
        install(['orbstack' if choice == '1' else 'docker-desktop'], cask=True)
        print('Open the installed app, complete its setup, then run the checks again.')


def homebrew(confirm=True):
    if shutil.which('brew'):
        print('Homebrew is already available.')
        return
    print('Official installer: https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh')
    with tempfile.TemporaryDirectory(prefix='banking-brew-') as directory:
        script = str(Path(directory) / 'install.sh')
        execute([['/usr/bin/curl', '-fsSL', 'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh', '-o', script],
                 ['/bin/bash', script]], confirm=confirm)


def install_all():
    activate_tools()
    runtime = next((name for name in ('OrbStack', 'Docker')
                    if any((base / f'{name}.app').exists()
                           for base in (Path('/Applications'), Path.home() / 'Applications'))), None)
    if runtime is None:
        choice = input('Docker runtime: 1 OrbStack [default], 2 Docker Desktop, 0 cancel: ').strip() or '1'
        if choice == '0':
            return
        if choice not in {'1', '2'}:
            raise ValueError('Choose 1 or 2 for the Docker runtime.')
        runtime = 'OrbStack' if choice == '1' else 'Docker'
    print('Install prerequisites: Apple command line tools if missing; Homebrew if missing; '
          'uv, Git, jq, OpenSSL, AWS CLI, gh, Terraform, Java 25, Node 24 and Session Manager plugin.')
    print(f'Docker runtime: {runtime}. Existing installations are reused. Installers may request your macOS password.')
    if input('Install all prerequisites on this Mac? Type yes: ').strip() != 'yes':
        return
    if not probe(['xcode-select', '-p'])[0]:
        execute([['xcode-select', '--install']], confirm=False)
        print('Complete the macOS command line tools dialog, then select Install all prerequisites again to continue.')
        return
    homebrew(confirm=False)
    activate_tools()
    brew = shutil.which('brew')
    if not brew:
        raise ValueError('Homebrew is not available after installation. Restart the menu and retry.')
    execute([[brew, 'install', 'uv', 'git', 'jq', 'openssl@3', 'awscli', 'gh',
              'hashicorp/tap/terraform', 'openjdk@25', 'node@24'],
             [brew, 'install', '--cask', 'session-manager-plugin']], confirm=False)
    if not any((base / f'{runtime}.app').exists()
               for base in (Path('/Applications'), Path.home() / 'Applications')):
        execute([[brew, 'install', '--cask', 'orbstack' if runtime == 'OrbStack' else 'docker-desktop']], confirm=False)
    execute([['open', '-a', runtime]], confirm=False)
    print('Complete any Docker app setup. The checks below may show Docker pending startup; rerun Check prerequisites once ready.')
    check()


def menu():
    if platform.system() != 'Darwin':
        raise ValueError('This prerequisite installer supports macOS only. Install the documented tools for your OS.')
    activate_tools()
    actions = {'1': check, '2': install_all}
    while True:
        print('\nmacOS prerequisites\n1. Check all tools and Docker readiness\n2. Install all prerequisites / resume installation\n0. Back')
        choice = input('Selection [0]: ').strip() or '0'
        if choice == '0':
            return
        try:
            if choice in actions:
                actions[choice]()
            else:
                print('Choose a listed number.')
        except (ValueError, OSError, subprocess.CalledProcessError) as exc:
            print(f'Prerequisite action failed: {exc}. Resolve the error and retry.')
