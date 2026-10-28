"""Offline release checks. Failure scenarios: see v0.1.3-plan.md and v0.1.2.md."""

import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(args, cwd=ROOT):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def main():
    for command in ('typecheck', 'build'):
        print(run(['npm', 'run', command], ROOT / 'plugin').strip())
    bundle = ROOT / 'plugin/dist/plugin.js'
    code = bundle.read_text()
    package = json.loads((ROOT / 'plugin/package.json').read_text())
    lock = json.loads((ROOT / 'plugin/package-lock.json').read_text())
    version = package['version']
    assert lock['version'] == lock['packages']['']['version'] == version
    assert code.startswith('//@name graphiti_memory\n')
    assert f'//@version {version}\n' in code and '//@api 3.0\n' in code
    expected_header = '\n'.join(
        line[3:] for line in (ROOT / 'plugin/src/index.ts').read_text().splitlines()
        if line.startswith('// //@')
    )
    assert code.startswith(expected_header + '\n')
    assert all(line.split()[2] in ('string', 'int') for line in expected_header.splitlines() if line.startswith('//@arg '))
    print(f'PASS: release metadata and package versions = {version}')

    python_files = list((ROOT / 'sidecar').glob('*.py'))
    python_files += list((ROOT / 'tools').glob('*.py'))
    python_files.append(Path(__file__))
    for file in python_files:
        ast.parse(file.read_text(), filename=str(file.relative_to(ROOT)))
    print(f'PASS: Python syntax ({len(python_files)} files; no imports/services)')

    with tempfile.TemporaryDirectory(prefix='graphmem-export-') as temp:
        fixture = Path(temp)
        chats = fixture / 'characters/合成角色--synthetic-id/chats'
        chats.mkdir(parents=True)
        messages = [
            {'role': 'user', 'data': '归还蓝色书。<Thoughts>隐藏推理</Thoughts><trim>忽略文字</trim>', 'time': 1},
            {'role': 'char', 'data': '约好明天见。<statusData>time:21:30|date:4月22日 周三|daysElapsed:16</statusData>', 'time': 2},
            {'role': 'user', 'data': '带上地图。', 'time': 3},
        ]
        (chats / '000.json').write_text(json.dumps({'message': messages}, ensure_ascii=False))

        def export(last, batch, name):
            output = fixture / name
            run([sys.executable, str(ROOT / 'tools/backfill.py'), 'export',
                 '--dump', str(fixture), '--char', 'synthetic-id', '--chat', '0',
                 '--last', str(last), '--batch', str(batch), '--out', str(output)])
            return [json.loads(line) for line in output.read_text().splitlines()]

        batched = export(3, 2, 'batched.jsonl')
        assert len(batched) == 2
        first = batched[0]
        assert '——用户——' in first['body'] and '——角色——' in first['body']
        assert '归还蓝色书。' in first['body'] and '约好明天见。' in first['body']
        for forbidden in ('<Thoughts>', '<statusData>', '<trim>', '隐藏推理', '忽略文字'):
            assert forbidden not in first['body']
        assert first['reference_time'] == '2026-04-22T21:30:00+08:00'
        assert '【剧情时间】' in first['body']
        assert batched[1]['reference_time'] == first['reference_time']
        assert '带上地图。' in batched[1]['body']
        print('PASS: export CLI batching, role tags, cleaning, story clock and carry-forward')
        short = export(2, 1, 'short.jsonl')
        full = export(3, 1, 'full.jsonl')
        assert short[0]['name'] != full[0]['name']
        assert [e['name'] for e in short] == [e['name'] for e in full[1:]]
        assert all(e['name'].startswith('bf-v2-') for e in full)
        print('PASS: overlapping export windows preserve identity without relative-name collisions')

    for doc in [ROOT / 'README.md', *sorted((ROOT / 'docs').rglob('*.md'))]:
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', doc.read_text()):
            if '://' not in target and not target.startswith('#'):
                assert (doc.parent / target.split('#')[0]).exists(), (doc.name, target)
    print('PASS: relative Markdown links resolve')
    browser_zip = bundle.parent / 'neo4j-browser.zip'
    browser_files = sorted((ROOT / 'docs/neo4j-browser').glob('*'))
    browser_files.append(ROOT / 'docs/verification/neo4j-browser-2026-10-28.md')
    with zipfile.ZipFile(browser_zip, 'w') as archive:
        for file in browser_files:
            info = zipfile.ZipInfo(file.relative_to(ROOT).as_posix())
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, file.read_bytes())
    with zipfile.ZipFile(browser_zip) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(browser_files)
    print(f'PASS: Browser query/guide archive ({len(browser_files)} public documentation files)')
    install_guide = bundle.parent / 'install-6001.md'
    shutil.copyfile(ROOT / 'docs/install-6001.md', install_guide)
    checksums = []
    for artifact in (bundle, browser_zip, install_guide):
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        checksums.append(f'{digest}  {artifact.name}\n')
        print(f'SHA256 {artifact.name}: {digest}')
    (bundle.parent / 'SHA256SUMS').write_text(''.join(checksums))
    print('PASS: offline release checks; product E2E is a separate release gate')


if __name__ == '__main__':
    main()
