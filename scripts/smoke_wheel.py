"""Install only a built wheel and its declared dependencies in a fresh environment.

Run from any directory: python scripts/smoke_wheel.py dist/devdash-*.whl
An optional --wheelhouse supports a genuinely clean offline install.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import venv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('wheel', type=Path)
    parser.add_argument('--wheelhouse', type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='devdash-wheel-') as directory:
        root = Path(directory)
        environment = root/'environment'
        venv.EnvBuilder(with_pip=True).create(environment)
        binary = environment/('Scripts' if os.name == 'nt' else 'bin')
        python = binary/('python.exe' if os.name == 'nt' else 'python')
        cli = binary/('devdash.exe' if os.name == 'nt' else 'devdash')
        clean_env = {key:value for key,value in os.environ.items() if key not in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV')}
        clean_env['PATH'] = str(binary) + os.pathsep + clean_env.get('PATH','')
        def run(argv):
            return subprocess.run([str(arg) for arg in argv], cwd=root, env=clean_env, check=True,
                                  capture_output=True, text=True, timeout=120)
        offline = ['--no-index','--find-links', str(args.wheelhouse.resolve())] if args.wheelhouse else []
        run([python,'-m','pip','install',*offline,wheel])
        location = run([python,'-I','-c','import devdash; print(devdash.__file__)']).stdout.strip()
        assert Path(location).is_relative_to(environment), location
        project = root/'fixture'
        project.mkdir()
        (project/'.devdash.toml').write_text('[commands]\ncheck = '+json.dumps([str(python),'-c','print("wheel works")'])+'\n')
        for flags in (['--help'], ['--version'], [project,'--status'], [project,'--doctor'], [project,'--run','check']):
            result = run([cli,*flags])
            print('PASS', ' '.join(str(flag) for flag in flags))
            if flags == ['--version']:
                print(result.stdout.strip())
        print('Imported installed package:', location)


if __name__ == '__main__':
    main()
