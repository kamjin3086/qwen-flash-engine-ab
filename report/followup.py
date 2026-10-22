"""Verified, curated pagoda evidence -> static report section and all-sample gallery.

No private workspace, engine, browser or live model is needed to rebuild these surfaces.
"""
from html import escape
import hashlib
import json
from pathlib import Path
from privacy import PAGES_URL

EXTRA_CSS = '''
.followup-pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;align-items:start}
.followup-pair figure{min-width:0}
.bare-sample{margin:0 0 22px;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.bare-sample figcaption{padding:10px 14px;font-size:.85rem;color:var(--mut)}
.bare-sample img{display:block;width:100%;height:auto}
.followup-pair h3{margin:0 0 6px}
@media(max-width:700px){.followup-pair{display:block}}
'''

STATUS = {
    'scene_visible': 'Scene visible',
    'runtime_error': 'Runtime error',
    'no_html_delivered': 'No HTML delivered',
    'incomplete_guard_termination': 'Incomplete answer: server loop guard',
    'partial_scene_visible': 'Partial scene visible',
    'scene_not_clearly_presented': 'Main scene not clearly presented',
    'browser_timeout_unverified': 'Unverified: browser timeout',
}


def load_evidence(repo):
    root = repo / 'results' / 'pagoda-followup'
    if not root.exists():
        return None
    manifest = json.loads((root / 'manifest.json').read_text())
    seen = set()
    for row in manifest['files']:
        rel = Path(row['path'])
        if rel.is_absolute() or '..' in rel.parts or str(rel) in seen:
            raise ValueError('invalid or duplicate follow-up evidence path')
        seen.add(str(rel))
        source = root / rel
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'follow-up evidence missing or symlinked: {rel}')
        data = source.read_bytes()
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError(f'follow-up evidence hash mismatch: {rel}')
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p != root / 'manifest.json'}
    if actual != seen:
        raise ValueError('follow-up manifest does not match the evidence tree')
    summary = json.loads((root / 'summary.json').read_text())
    names = ['original-01'] + [f'sample-{i:02}' for i in range(1, 6)]
    for engine in ('halogen', 'kyojin'):
        rows = summary['bare'][engine]
        if [r['name'] for r in rows] != names:
            raise ValueError('follow-up must include every planned bare sample')
        for row in rows:
            folder = root / 'bare' / engine / row['name']
            text = (folder / 'answer.txt').read_bytes()
            meta = json.loads((folder / 'result.json').read_text())
            if hashlib.sha256(text).hexdigest() != row['answer_sha256']:
                raise ValueError('follow-up answer hash disagrees with summary')
            if meta['usage']['completion_tokens'] != row['completion_tokens']:
                raise ValueError('follow-up token count disagrees with captured record')
        record = json.loads((root / 'agent' / engine / 'result.json').read_text())
        agent = summary['clean_agent'][engine]
        for key in ('outputTokens', 'httpRequests', 'stop', 'wall_s'):
            if record[key] != agent[key]:
                raise ValueError(f'follow-up agent {key} disagrees with captured record')
        page = (root / 'agent' / engine / 'final.html').read_bytes()
        if hashlib.sha256(page).hexdigest() != agent['final_html_sha256']:
            raise ValueError('follow-up final page disagrees with summary')
    return summary


def url(path):
    return '../results/pagoda-followup/' + path


def stop_label(agent):
    return '12-response cap (not a token/time limit)' if agent['stop_detail'] == 'assistant_response_cap_12' else 'normal completion'


def agent_cards(summary):
    cards = []
    for engine in ('halogen', 'kyojin'):
        a = summary['clean_agent'][engine]
        base = 'agent/' + engine
        cards.append(f'''<figure class="art">
<figcaption><h3>{engine.title()}: clean Pi SDK trial</h3>
{a['outputTokens']:,} output tokens · {a['httpRequests']} model requests · {a['edits']} local edits<br>
<strong>Agent stop:</strong> {escape(stop_label(a))}<br>
<strong>Final browser observation:</strong> scene visible; no current-route runtime error.<br>
<a href="{url(base + '/final.html')}" target="_blank" rel="noopener">Open final animated page</a> ·
<a href="{url(base + '/result.json')}">Run record</a></figcaption>
<img class="shot" loading="lazy" src="{url(base + '/final.png')}" alt="{engine.title()} final pagoda and garden in the clean Pi SDK trial">
</figure>''')
    return '<div class="followup-pair">' + ''.join(cards) + '</div>'


def overview(summary):
    return f'''<section id="pagoda-follow-up">
<h2>Pagoda follow-up — {escape(summary['date'])}</h2>
<p>The original incomplete Kyojin answer reproduced byte-for-byte with server loop-guard
metadata. That is a real observation, not a general quality verdict: both complete setups
produced viewable pages in a separate bounded Pi SDK workflow.</p>
{agent_cards(summary)}
<p>These are the final files from one clean agent trial per engine, not selected best-of
samples. Bare output and tool-assisted repair answer different questions. The packs and
chat templates differ. No aesthetic score or population success-rate estimate is claimed.</p>
<p><a href="pagoda-followup.html">Inspect all 12 bare samples, protocol and agent evidence</a> ·
<a href="{url('summary.json')}">Follow-up summary JSON</a> ·
<a href="{url('manifest.json')}">Evidence manifest</a></p>
<p class="sub">The original 111-row performance matrix above is unchanged. Follow-up
bare/pilot timings were affected by test-browser CPU contention and are not clean speed
comparisons. Clean agent trials closed each browser before inference and passed per-request
CPU gates; their wall times still include separately recorded parent/tool delay.</p>
</section>'''


def markdown(summary, repo_url):
    lines = ['## Pagoda follow-up — ' + summary['date'], '',
             'The old greedy Kyojin answer reproduced byte-for-byte with server loop-guard metadata. '
             'Both setups produced viewable final pages in the separate clean Pi SDK trial; '
             'these are different packs/templates and not a model-quality ranking.', '',
             '| Engine | Output tokens | Model requests | Agent stop | Final browser observation |',
             '|---|---:|---:|---|---|']
    for engine in ('halogen', 'kyojin'):
        a = summary['clean_agent'][engine]
        lines.append(f'| {engine.title()} | {a["outputTokens"]:,} | {a["httpRequests"]} | {stop_label(a)} | Scene visible; no current-route runtime error |')
    lines += ['', 'All 12 bare samples, including failures and an unverified browser timeout, plus protocol and evidence:',
              f'{PAGES_URL}/docs/pagoda-followup.html',
              f'Curated evidence: {repo_url}/tree/main/results/pagoda-followup', '',
              'The original performance matrix is unchanged. Bare/pilot timings are not clean speed comparisons. '
              'The clean agent wall times include parent/tool delay; one case each does not rank engine speed.', '']
    return '\n'.join(lines)


def gallery(summary, css):
    pieces = []
    for index in range(6):
        title = 'Original-condition repeat: greedy, no tools' if index == 0 else f'Fixed seed {4100 + index}: stochastic, no tools'
        pair = []
        for engine in ('halogen', 'kyojin'):
            row = summary['bare'][engine][index]
            base = 'bare/' + engine + '/' + row['name']
            image = ('<p>No verified screenshot. Browser navigation timed out; cause not established.</p>'
                     if row['status'] == 'browser_timeout_unverified' else
                     f'<img loading="lazy" src="{url(base + "/browser.png")}" alt="{escape(engine.title() + " " + row["name"] + ": " + STATUS[row["status"]])}">')
            pair.append(f'''<figure class="bare-sample"><figcaption><h3>{engine.title()}: {escape(STATUS[row['status']])}</h3>
<p>{escape(row['note'])}</p>
{row['completion_tokens']:,} output tokens · complete HTML: {str(row['closing_html']).lower()}<br>
<a href="{url(base + '/page.html')}" target="_blank" rel="noopener">Open generated page (may fail)</a> ·
<a href="{url(base + '/answer.txt')}">Raw answer</a> ·
<a href="{url(base + '/request.json')}">Request</a> ·
<a href="{url(base + '/response.sse')}">Captured SSE</a> ·
<a href="{url(base + '/result.json')}">Capture record</a></figcaption>{image}</figure>''')
        pieces.append('<h2>' + title + '</h2><div class="followup-pair">' + ''.join(pair) + '</div>')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pagoda follow-up — all samples, Halogen and Kyojin</title><style>{css}{EXTRA_CSS}</style></head>
<body><main><p><a href="index.html#pagoda-follow-up">Back to the comparison report</a></p>
<h1>Pagoda follow-up — all samples</h1>
<p>No live frames: opening this page does not run model-generated animations. Click-through
pages use external CDNs, may fail, and can consume substantial CPU; close them when done.</p>
<p>All planned samples are shown, not a best-of selection. Complete HTML does not guarantee
a working scene. Outcomes are observations, not aesthetic scores or a stable success-rate estimate.</p>
<h2>Protocol and scope</h2><p>{escape(summary['method']['bare'])}</p>
<p>{escape(summary['method']['agent'])}</p><p>{escape(summary['method']['browser'])}</p>
<p>Same pinned images/packs as the original run, 262144 context capacity, vision enabled;
Kyojin sessions=1 with disk streaming. <a href="{url('protocol.md')}">Protocol, exclusions and replay limitations</a> ·
<a href="{url('manifest.json')}">All evidence hashes</a> · <a href="{url('harness/pi-agent-clean.mjs.txt')}">Archived SDK harness source</a></p>
<h2>Clean Pi SDK final pages</h2>{agent_cards(summary)}
<p>Halogen stopped at its 12-response cap; its final post-run check is independent of the
agent's two inspections. Kyojin ended normally; its final file matches its last inspection.
These are one case each, not an engine-quality verdict. Interactions were not exhaustively tested.</p>
{''.join(pieces)}
<h2>How to read these results</h2>
<p>Halogen delivered complete HTML in 3/5 stochastic samples; Kyojin in 5/5. This is not a
3/5 versus 5/5 working-page comparison: runtime errors, partial scenes and the unverified
browser timeout remain visible above. Bare/pilot timings were contaminated by animated
browser CPU load and are not used to compare speed. A same-seed technical recapture after
a collection cutoff is disclosed in the protocol, not counted as an engine failure.</p>
<p>AI assisted the test planning, scripts, troubleshooting, analysis and write-up. That is
not independent validation; the captured records and images are provided for inspection.</p>
</main></body></html>'''
