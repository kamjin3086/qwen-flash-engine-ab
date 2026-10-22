#!/usr/bin/env python3
"""Freeze a scrubbed pagoda follow-up evidence set, never the whole experiment folder.

The report rebuild reads only results/pagoda-followup, so public readers do not need the
private experimental workspace. Explicit operator action is needed to refresh this set.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'report'))
import privacy


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--dest', default='results/pagoda-followup')
    args = p.parse_args()
    src, dest = Path(args.source).resolve(), Path(args.dest).resolve()
    if dest == src or src in dest.parents or dest in src.parents:
        raise SystemExit('source and destination must be disjoint trees')
    staging = dest.with_name(dest.name + '.staging')
    if staging.exists():
        raise SystemExit(f'remove or inspect existing staging directory first: {staging}')
    staging.mkdir(parents=True)
    files = []

    def put(rel, body):
        if isinstance(body, str):
            for engine in ('halogen', 'kyojin'):
                body = body.replace(str(src / f'{engine}-agent-clean' / 'workspace'), '<workspace>')
            body = privacy.scrub(body)
            problems = privacy.scan(str(rel), body, allow=privacy.PUBLIC_URLS)
            if problems:
                raise ValueError('\n'.join(problems))
            body = body.encode()
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        files.append({'path': str(rel), 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})

    def copy(source, rel):
        if source.suffix == '.png':
            put(rel, source.read_bytes())
        else:
            put(rel, source.read_text())

    summary = json.loads((src / 'summary.json').read_text())
    summary['publication'] = 'curated follow-up; separate from the original performance matrix'
    summary['date'] = '2026-10-22'
    summary['engines'] = {
        'halogen': {'image_digest': 'sha256:2e98dc53ed4a43b5600b11a80852eedfa573f4ffc3f10c64da01245f2a3217fc', 'slots': 4},
        'kyojin': {'image_digest': 'sha256:a0c48fea49a605da3e5eaeee4fcd82aa5a8591063976bbbbbca7c2c4f9c20b51', 'sessions': 1, 'EXL3_NGRAM_STREAM': '1'}}
    summary['excluded_attempts'] = [
        'SDK tool-activation preflight errors: not engine failures.',
        '32K/10-minute pilot: no local editing, unequal browser delays.',
        '64K Halogen v2: animated test browser CPU contention; no matched Kyojin request.',
        'Bare Kyojin seed 4104: first collection interrupted by the parent command limit; one same-seed technical recapture, not a quality retry.',
        'Preliminary 1280x633 screenshots excluded; comparison frames are 1280x900.']
    summary['method'] = {
        'prompt': (src.parents[1] / 'docs/prompts/pagoda.txt').read_text().strip(),
        'bare': 'One original greedy repeat and five stochastic no-tools samples per engine; temperature 0.7, top_p 0.8, top_k 20, min_p 0, seeds 4101-4105, thinking off, max_tokens 16384.',
        'agent': 'One real Pi SDK trial per engine, read/write/unique-edit/inspect tools, seed 5101, same stochastic sampling, 65536 output tokens total, 16384 per request, 1200 seconds, 12 assistant responses, 3 inspections.',
        'browser': '1280x900, observe after a 10-second window, save screenshot and current-route errors. No human repair hints. Close each owned browser before inference; sample CPU before every model request.',
        'limits': 'Different packs/templates remain. No aesthetic score or population success-rate estimate. Interactions not exhaustively tested. Blank/loading/error/timeout outcomes are distinct.',
        'privacy': 'Text records have host paths and operator identifiers scrubbed; request workspace paths become <workspace>. PNG bytes are unchanged. Manifest hashes describe these published bytes, not unsanitized private records.'}
    put(Path('summary.json'), json.dumps(summary, indent=2) + '\n')
    copy(src / 'evaluations.json', Path('evaluations.json'))
    for engine in ('halogen', 'kyojin'):
        for name in ['original-01'] + [f'sample-{i:02}' for i in range(1, 6)]:
            folder = src / engine / name
            for filename in ['request.json', 'response.sse', 'answer.txt', 'reasoning.txt', 'page.html', 'result.json', 'browser.png']:
                source = folder / filename
                if source.exists():
                    copy(source, Path('bare') / engine / name / filename)
        folder = src / f'{engine}-agent-clean'
        base = Path('agent') / engine
        for filename in ['protocol.json', 'system.txt', 'active-tools.json', 'messages.jsonl', 'result.json']:
            copy(folder / filename, base / filename)
        for source in sorted(folder.glob('request-*')):
            if source.suffix in ('.json', '.sse'):
                copy(source, base / source.name)
        copy(folder / 'workspace/index.html', base / 'final.html')
        shot = folder / ('final-browser.png' if engine == 'halogen' else 'inspect-02/browser.png')
        copy(shot, base / 'final.png')
        for source in sorted((folder / 'versions').glob('*')):
            copy(source, base / 'versions' / source.name)
        gates = [json.loads(line) for line in (folder / 'cpu-gates.jsonl').read_text().splitlines()]
        for gate in gates:
            gate.pop('test_chrome_pids', None)
        put(base / 'cpu-gates.json', json.dumps(gates, indent=2) + '\n')
        for ticket in sorted(folder.glob('inspect-*')):
            for filename in ['page.html', 'browser.png', 'inspection-timing.json']:
                copy(ticket / filename, base / ticket.name / filename)
            feedback = json.loads((ticket / 'feedback.json').read_text())
            put(base / ticket.name / 'browser-observation.json', json.dumps({
                'viewport': [1280, 900], 'observation_window_s': 10, 'browser_closed_after_capture': True,
                'text': feedback['text'], 'screenshot': 'browser.png'}, indent=2) + '\n')
    protocol = '# Pagoda follow-up protocol — 2026-10-22\n\n'
    protocol += '\n\n'.join(f'## {key.title()}\n\n{value}' for key, value in summary['method'].items())
    protocol += ('\n\n## Interpretation and exclusions\n\n'
                 'Both final agent pages are inspectable; a cap stop is separate from page usability. '
                 'The earlier failing greedy Kyojin answer was reproduced byte-for-byte with loop-guard metadata. '
                 'No guard-disabling experiment or aesthetic ranking was performed. '
                 'Bare/pilot timings are not clean comparative measurements.\n\n')
    protocol += '\n'.join('- ' + item for item in summary['excluded_attempts'])
    protocol += ('\n\n## Rebuild versus repeat\n\n'
                 'The report rebuild verifies this evidence manifest; it does not contact a model or run generated pages. '
                 'Archived harness sources are in harness/*.txt: local SDK installation paths are redacted, '
                 'so they are source records, not turnkey executable scripts. Repeating live agent trials '
                 'requires a compatible Pi SDK installation, a native browser feedback adapter and safe engine scheduling. '
                 'Actual model HTTP requests, SSE responses, tool transcripts, file versions, timing and CPU gates '
                 'are retained so the workflow can be inspected without assuming an unpublished daily-agent setup.\n')
    put(Path('protocol.md'), protocol)
    for filename in ['pi-agent-clean.mjs', 'cpu_gate.py', 'return_feedback.py', 'capture.py']:
        put(Path('harness') / (filename + '.txt'), (src / filename).read_text())
    # Host records and pilot folders deliberately do not cross this boundary.
    manifest = {'schema': 1, 'date': '2026-10-22', 'files': sorted(files, key=lambda x: x['path'])}
    (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if dest.exists():
        shutil.rmtree(dest)
    staging.rename(dest)
    print(f'{dest}: {len(files)} curated files; no private experiment/history mirror')


if __name__ == '__main__':
    main()
