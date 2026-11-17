# Kaggle CPU workflow for RQ1

This guide prepares and runs the experiment **only when you execute the live-run cells**. The six-case development run is for debugging and is not a research sample. The final experiment uses all 40 original cases and eight samples per channel. Set Kaggle Notebook accelerator to **None (CPU)** and enable **Internet**. Add a Kaggle Secret named `GROQ_API_KEY`. Do not paste the secret in the notebook or print environment variables.

## 1. Clone and pin the tested Stage 5 commit

Run this `%%bash` cell. It locates the unique first-parent commit with the requested Stage 5 title immediately after the known Stage 4 commit, then checks it out detached. Check the printed SHA against the Stage 5 commit hash supplied with the implementation. This resolves the pin without embedding a commit's own hash inside itself. If the branch has been rewritten and the commit is no longer in its first-parent history, this cell stops.

```bash
%%bash
set -euo pipefail
cd /kaggle/working
git clone --branch thesis-experiments https://github.com/dinar5150/dualify-thesis.git
cd dualify-thesis
RQ1_PIN="$(git log --first-parent --format='%H %P%x09%s' origin/thesis-experiments | python3 -c '
import sys
parent = "3435cbb46e13e78886d6b18aba61fb38820615cf"
title = "feat(rq1): add diagnostics and Kaggle execution workflow"
matches = []
for line in sys.stdin:
    parts = line.rstrip("\n").split("\t", 1)
    if len(parts) == 2:
        hashes, subject = parts
        fields = hashes.split()
        if len(fields) == 2 and fields[1] == parent and subject == title:
            matches.append(fields[0])
if len(matches) != 1:
    raise SystemExit("Expected exactly one Stage 5 commit on the branch")
print(matches[0])
')"
git checkout --detach "$RQ1_PIN"
test "$(git rev-parse HEAD^)" = 3435cbb46e13e78886d6b18aba61fb38820615cf
printf 'Pinned SHA: %s\n' "$RQ1_PIN"
python3 --version
```

## 2. Install the locked dependencies

Run this `%%bash` cell. The lockfile pins `z3-solver` 4.16.0.0; the runtime check must report 4.16.0. Do not change the lockfile or Z3. Poetry uses the in-project `.venv` configured by the repository.

```bash
%%bash
set -euo pipefail
cd /kaggle/working/dualify-thesis
python3 -m pip install 'poetry==2.1.4'
poetry install --only main --no-interaction
poetry run python -c 'import sys, z3; print(sys.version); print("Z3:", z3.get_version_string()); assert z3.get_version_string() == "4.16.0"'
```

## 3. Load the secret and check the requested model

Run this Python cell. It prints only HTTP status and the requested model's listing status, never the credential or response body. A listed model is not a guarantee of quota; if the request fails or the model is absent, stop and investigate access rather than substitute another model.

```python
import os
import requests
from kaggle_secrets import UserSecretsClient

os.environ.pop('DUALIFY_API_KEY', None)
os.environ.pop('DUALIFY_DEBUG_LLM_RAW', None)
os.environ['GROQ_API_KEY'] = UserSecretsClient().get_secret('GROQ_API_KEY')
os.environ['DUALIFY_OPENAI_USE_CHAT'] = '1'
try:
    response = requests.get(
        'https://api.groq.com/openai/v1/models',
        headers={'Authorization': 'Bearer ' + os.environ['GROQ_API_KEY']},
        timeout=20,
    )
    print('Groq model-list HTTP status:', response.status_code)
    response.raise_for_status()
    available = any(item.get('id') == 'qwen/qwen3.8-27b'
                    for item in response.json().get('data', []))
    print('Requested model listed:', available)
    if not available:
        raise RuntimeError('Requested model not listed; stop and check access.')
except requests.RequestException:
    raise RuntimeError('Groq model-list request failed; check access without printing the key.') from None
```

## 4. Define a timed command helper

This Python cell uses `time.monotonic()` and does not rely on `/usr/bin/time`. Output, a redacted console log, and manifests are stored outside the clone. An exit code of 1 can indicate a completed failed candidate; inspect the saved results before proceeding.

```python
import subprocess
import time
from pathlib import Path

REPO = Path('/kaggle/working/dualify-thesis')
ARTIFACTS = Path('/kaggle/working/rq1-artifacts')
ARTIFACTS.mkdir(exist_ok=True)

def run_command(arguments):
    started = time.monotonic()
    command = ['poetry', 'run', 'python', *map(str, arguments)]
    with (ARTIFACTS / 'commands.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=REPO, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert process.stdout is not None
        for line in process.stdout:
            for name in ('GROQ_API_KEY', 'DUALIFY_API_KEY'):
                secret = os.environ.get(name, '')
                if secret:
                    line = line.replace(secret, '[REDACTED]')
            print(line, end='')
            log.write(line)
            log.flush()
        code = process.wait()
        summary = f'Exit code: {code}; elapsed seconds: {time.monotonic() - started:.2f}\n'
        print(summary, end='')
        log.write(summary)
    return code

common = ['--model', 'qwen/qwen3.8-27b', '--provider', 'openai',
          '--base-url', 'https://api.groq.com/openai', '--temperature', '0.7',
          '--inter-request-seconds', '10']
```

## 5. Six-case development smoke test

First inspect the plan, then explicitly run the first two attempts. The original repair temperature remains 0.0; only the initial request uses 0.7. The smoke test is separate from the full experiment.

```python
run_command(['scripts/run_rq1.py', '--dry-run', '--dev', '--samples', '1'])
dev_dir = ARTIFACTS / 'dev-generation'
run_command(['scripts/run_rq1.py', '--run', '--dev', '--samples', '1',
             '--output-dir', dev_dir, '--max-new-attempts', '2', *common])
```

Verify that a manifest and at most two terminal results exist, then resume. Running the resume cell multiple times is safe; finished slots and terminal failures are not repeated.

```python
import json
manifest = json.loads((dev_dir / 'manifest.json').read_text())
print('Experiment ID:', manifest['experiment_id'])
print('Selected cases:', len(manifest['configuration']['selected_case_ids']))
print('Terminal result files:', len(list(dev_dir.glob('attempts/*/result.json'))))
run_command(['scripts/run_rq1.py', '--run', '--resume', '--dev', '--samples', '1',
             '--output-dir', dev_dir, '--max-new-attempts', '2', *common])
```

If an attempt was interrupted, its start marker remains and the slot is retried. A completed API failure remains terminal. For a new smoke test use a new directory, not the same directory without `--resume`.

## 6. Full 40-case experiment

Confirm the plan shows 40 cases and 640 attempts. This next cell **starts live Groq generation**; run it only when ready. It limits the first invocation to 20 new attempts, not a benchmark subset. Each invocation can take a long time because the original provider retry policy is retained.

```python
run_command(['scripts/run_rq1.py', '--dry-run', '--samples', '8'])
full_dir = ARTIFACTS / 'full-generation'
run_command(['scripts/run_rq1.py', '--run', '--samples', '8', '--output-dir', full_dir,
             '--max-new-attempts', '20', *common])
```

Continue with this cell until it reports 640 terminal results. Remove `--max-new-attempts` to process all remaining slots in one invocation. Failed terminal attempts count toward 640 and appear in the results; they are not silently regenerated.

```python
run_command(['scripts/run_rq1.py', '--run', '--resume', '--samples', '8',
             '--output-dir', full_dir, '--max-new-attempts', '20', *common])
print('Terminal results:', len(list(full_dir.glob('attempts/*/result.json'))), '/ 640')
```

## 7. Resume in another Kaggle session

Before ending a session, export the artifact ZIP as below and save it outside the ephemeral notebook. In the new session, re-run sections 1–4 with the **same pinned commit**, environment, Kaggle image/Python build, Poetry lockfile, model, sample count, temperature, pacing, Z3 version and `DUALIFY_OPENAI_USE_CHAT=1`. Add the prior ZIP as a Kaggle input or otherwise make it available; set `previous_zip` to its actual path, then extract it to restore the full artifact directory:

```python
import zipfile
previous_zip = '/kaggle/input/REPLACE_WITH_YOUR_DATASET/rq1-export.zip'
with zipfile.ZipFile(previous_zip) as archive:
    archive.extractall(ARTIFACTS)
full_dir = ARTIFACTS / 'full-generation'
assert (full_dir / 'manifest.json').is_file()
```

Use the full resume cell above. The runner rejects incompatible manifest settings, source/input hashes, commit, Python or Z3 versions; do not edit the manifest to bypass that check. Never run two writers against copies of the same experiment, and do not merge independently generated output directories.

## 8. Offline evaluation, analysis and diagnostics

The following cells use saved results and the original gold scorer; they do not make LLM calls. Use new output directory names each time: these scripts do not overwrite previous reports. Do not analyze untrusted model-produced formulas without reviewing the original solver's use of Python `eval`.

```python
evaluation_dir = ARTIFACTS / 'full-evaluation'
analysis_dir = ARTIFACTS / 'full-analysis'
diagnostics_dir = ARTIFACTS / 'full-diagnostics'
run_command(['scripts/evaluate_rq1.py', '--run-dir', full_dir,
             '--output-dir', evaluation_dir])
run_command(['scripts/analyze_rq1.py', '--evaluation', evaluation_dir / 'evaluation.json',
             '--output-dir', analysis_dir])
run_command(['scripts/diagnose_rq1.py', '--run-dir', full_dir,
             '--evaluation', evaluation_dir / 'evaluation.json', '--output-dir', diagnostics_dir])
```

Evaluation uses the gold and benchmark from the pinned repository and checks them against the original commit. Final macro pass@k is withheld until all 40 tasks have eight terminal outcomes for the relevant channel. Unknowns are inconclusive, not Z3 bugs. Inspect the reports and all flagged uncertainty before drawing conclusions.

## 9. Export the artifacts

This ZIP includes only `rq1-artifacts`, not the repository, environment, `.env`, or Kaggle Secrets. It includes generation data and any reports created. Download the ZIP from Kaggle's Output panel, and retain it between sessions.

```python
import shutil
zip_path = shutil.make_archive('/kaggle/working/rq1-export', 'zip', root_dir=ARTIFACTS)
print('Saved:', zip_path)
```
