#!/usr/bin/env python3
"""Create an isolated build tree; never modify the pinned dependency checkout."""
from pathlib import Path
import io
import shutil
import subprocess
import tarfile
import tempfile


def prepare():
    root = Path(__file__).resolve().parent.parent
    dependency = root / 'authelia'
    subprocess.run(['git', '-C', str(dependency), 'rev-parse', '--verify', 'HEAD'],
                   check=True, stdout=subprocess.DEVNULL)
    build = root / '.build'
    build.mkdir(exist_ok=True)
    source = Path(tempfile.mkdtemp(prefix='authelia-', dir=build))
    archive = subprocess.check_output(['git', '-C', str(dependency), 'archive', 'HEAD'])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for item in tar.getmembers():
            target = (source / item.name).resolve()
            if not target.is_relative_to(source.resolve()) or item.issym() or item.islnk():
                raise ValueError('Unsafe dependency archive entry')
        tar.extractall(source)
    subprocess.run(['git', 'init', '--quiet', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'apply', str(root / 'providers/authelia/adapter.patch')], check=True)
    shutil.copytree(root / 'src/emailotp', source / 'internal/emailotp')
    return source


if __name__ == '__main__':
    print(prepare())
