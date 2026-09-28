import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

config = Path(__file__).resolve().parent
meta = json.loads((config / 'case.json').read_text())
work = Path(sys.argv[1]).resolve()
evidence = Path(sys.argv[2]).resolve()
evidence.mkdir(parents=True, exist_ok=True)
python = sys.executable
source = work / meta['source']
fixed = source.read_bytes()
summary = {}


def environment(root):
    return dict(os.environ, PYTHONPATH=str(root / meta['pythonpath']))


def run(label, args, expected=0, root=work):
    with (evidence / (label + '.log')).open('w') as log:
        result = subprocess.run(args, cwd=root, env=environment(root),
                                stdout=log, stderr=subprocess.STDOUT, timeout=300)
    output = (evidence / (label + '.log')).read_text(errors='replace')
    print(label, result.returncode, output[-250:], flush=True)
    assert result.returncode == expected, (label, output[-8000:])


def test(label, paths, expected=0, root=work, coverage=False):
    args = [python, str(config / 'pytest_runner.py'), *paths, '-q', '--tb=short',
            '--junitxml=' + str(evidence / (label + '.xml'))]
    if coverage:
        module = 'skai' if meta['repo'].endswith('/skai') else 'language.casper'
        args += ['--cov=' + module, '--cov-branch',
                 '--cov-report=json:' + str(evidence / 'coverage.json')]
    run(label, args, expected, root)
    suites = list(ET.parse(evidence / (label + '.xml')).getroot().iter('testsuite'))
    counts = [sum(int(s.attrib.get(k, 0)) for s in suites)
              for k in ('tests', 'failures', 'errors', 'skipped')]
    summary[label] = counts
    print(label, counts, flush=True)
    return counts


assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=work,
                               text=True).strip() == meta['head']
print('TESTED SOURCE', meta['head'], flush=True)
run('dependencies', [python, '-m', 'pip', 'freeze'])
run('dependency-check', [python, '-m', 'pip', 'check'])
count, failures = meta['new_counts']
assert test('fixed-focused', [meta['test']]) == [count, 0, 0, 0]
assert test('fixed-suite', meta['suite_files'], coverage=True) == [meta['suite_count'], 0, 0, 0]
original = subprocess.check_output(['git', 'show', meta['base'] + ':' + meta['source']], cwd=work)
try:
    source.write_bytes(original)
    assert test('original-focused', [meta['test']], expected=1) == [count, failures, 0, 0]
    assert test('baseline-suite', meta['suite_files'][1:]) == [meta['suite_count'] - count, 0, 0, 0]
finally:
    source.write_bytes(fixed)
assert test('restored-focused', [meta['test']]) == [count, 0, 0, 0]
assert source.read_bytes() == fixed
run('source-restored', ['git', 'diff', '--exit-code'])
run('test-lint', [python, '-m', 'ruff', 'check', meta['test']])
run('source-lint', [python, '-m', 'ruff', 'check', '--select', 'E9,F63,F7,F82', meta['source']])
run('patch-check', ['git', 'diff', '--check', meta['base']])
run('compile', [python, '-m', 'py_compile', meta['source'], meta['test']])
with tempfile.TemporaryDirectory() as directory:
    exported = Path(directory) / 'source'
    shutil.copytree(work, exported, ignore=shutil.ignore_patterns(
        '.git', '__pycache__', '*.egg-info', '.pytest_cache', '.coverage'))
    module = 'skai.buildings' if meta['repo'].endswith('/skai') else 'language.casper.evaluate.top_metrics'
    code = ("import importlib; from pathlib import Path; "
            f"m=importlib.import_module({module!r}); p=Path(m.__file__).resolve(); "
            f"print(p); assert p.is_relative_to(Path({str(exported)!r}))")
    run('exported-import', [python, '-c', code], root=exported)
    assert test('exported-suite', meta['suite_files'], root=exported) == [meta['suite_count'], 0, 0, 0]
(evidence / 'summary.json').write_text(json.dumps(summary, indent=2))
print('VALIDATION COMPLETE', meta['head'], flush=True)
