# NewsCard Studio

NewsCard Studio turns fresh RSS and Hacker News stories into 1080x1350 Instagram news cards. It runs entirely on GitHub: Actions fetches and renders, the repo stores JSON and card images, and GitHub Pages hosts the mobile dashboard.

There is no server to keep alive and no database to provision. The public GitHub repository is the backend.

## How it works

1. A schedule or the dashboard starts `.github/workflows/tick.yml`.
2. `core/news.py` fetches recent stories, filters muted topics and removes duplicates.
3. `core/llm.py` picks a story and writes the card copy. If every model is missing or down, a rule-based editor takes over.
4. `core/images.py` tries Unsplash, the article photo, Pixabay, Wikimedia, then a generated background.
5. `core/design.py` tries model-written HTML and falls back to a verified local template.
6. `core/render.py` screenshots the card in headless Chrome at 1080x1350.
7. The card is either published with `instagrapi`, queued for approval, or generated as a preview.
8. Data and card files are committed back to the repo. Pages serves the dashboard and card images.

The generated card HTML is untrusted data. Scripts, event handlers, frames and remote images are removed before rendering. Instagram credentials are never sent to the dashboard.

## Repository layout

```text
core/                  News, LLM, image, design, render, scheduler and publishing code
data/config.json       Dashboard-editable settings
data/queue.json        Cards waiting for approval
data/history.json      Posted and generated card records
data/status.json       Live run progress for the dashboard
docs/                  GitHub Pages dashboard and PWA files
docs/cards/            Generated card images served by Pages
docs/brand/logo.png    Optional brand logo
tests/                 Offline Python self-tests
core/env.py            Local .env loader and status check
.env.example           Copy to .env for local provider keys
tools/get_session.py   One-time local Instagram session helper
.github/workflows/     Scheduled and manual pipeline runner
```

## Quick start

### 1. Publish the repository

Create a GitHub repository and push this project. A public repository is recommended because Actions and Pages are free for public repos.

Open **Settings > Pages**, choose **Deploy from a branch**, then select your default branch and the **`/docs`** folder. Do not choose "GitHub Actions" unless you add a Pages deployment workflow; this project deploys the static `docs/` folder directly.

The dashboard will be at:

```text
https://<owner>.github.io/<repo>/
```

Wait for the first Pages deployment before opening it.

### 2. Create a dashboard token

Create a fine-grained personal access token limited to this repository with:

- **Contents: Read and write** so the dashboard can read and update `data/`, cards and the logo.
- **Actions: Read and write** so the dashboard can start workflow runs and check them.

The token is stored only in your browser's `localStorage`. It is not committed and the Actions workflow does not receive it.

### 3. Connect the dashboard

Open the Pages URL and complete onboarding:

1. Enter `owner/repo` and the token.
2. Confirm the repository and branch.
3. Choose topics, posting times and a mode.

The dashboard writes the initial `data/config.json` through the GitHub API. The token itself is not written into the repo.

### 4. Enable Actions

Open **Actions**, select **NewsCard tick**, and enable the workflow if GitHub asks.

The workflow uses its built-in `GITHUB_TOKEN` with `contents: write` to commit data and cards. No extra token is needed for the pipeline. If your organization restricts workflow permissions, enable read/write workflow permissions under **Settings > Actions > General > Workflow permissions**.

### 5. Test a preview

In the dashboard choose **Preview a card**. This starts `generate_preview`, which always queues a card and never posts. Check the Queue and review the image.

You can also run it locally after installing the dependencies and Chrome (see below):

```powershell
.\.venv\Scripts\python.exe -m core.run --action generate_preview
```

## Secrets and optional providers

Add secrets under **Settings > Secrets and variables > Actions**. Nothing here is required for a rule-based, generated-background preview, except that news feeds need outbound internet access.

### Text models

Providers are tried in this order: NVIDIA, OpenCode, Gemini, Groq. Each configured provider needs its key and model. A missing key is skipped silently. The rule-based editor is always the final fallback.

| Provider | Required secrets | Optional |
| --- | --- | --- |
| NVIDIA | `NVIDIA_API_KEY`, `NVIDIA_MODEL` | `NVIDIA_BASE_URL` |
| OpenCode | `OPENCODE_API_KEY`, `OPENCODE_MODEL`, `OPENCODE_BASE_URL` | |
| Gemini | `GEMINI_API_KEY`, `GEMINI_MODEL` | `GEMINI_BASE_URL` |
| Groq | `GROQ_API_KEY`, `GROQ_MODEL` | `GROQ_BASE_URL` |

The provider order is stored in `data/config.json` and can be changed in Settings.

### Images

- `UNSPLASH_ACCESS_KEY`: optional. Unsplash images must be at least 1080px wide, must not have been used in the last 30 days, and always keep the Unsplash credit line.
- `PIXABAY_API_KEY`: optional.
- Wikimedia and article `og:image` need no key.
- The generated abstract background is always available and is always tried last.

Respect each provider's license and attribution requirements. Unsplash attribution is required by the project and is appended to the caption and card.

### Instagram

Publishing uses the unofficial `instagrapi` library and a saved session cookie. Generate the session once on your own machine:

```powershell
.\.venv\Scripts\python.exe tools\get_session.py
```

The script writes `ig_session.json` locally. That file is gitignored and is a credential. Add its entire contents as the `IG_SESSION_JSON` secret. You can also import a browser `sessionid` with:

```powershell
.\.venv\Scripts\python.exe tools\get_session.py --sessionid
```

Optional fallback secrets:

- `IG_USERNAME`
- `IG_PASSWORD`

These are used only for one automatic session refresh when Instagram reports that the session is invalid. Normal runs never log in with a password. If a challenge appears, approve it in the Instagram app, wait, run `tools/get_session.py` again, and replace the secret. Do not retry in a loop.

Use a dedicated account and understand that unofficial automation can trigger checkpoints or rate limits. The project adds a random 5-20 second delay but cannot guarantee Instagram will never challenge the account.

## Posting modes

Set the mode in the dashboard:

- **Review first** (`approve`): cards are queued for review. Approve from the Queue to publish.
- **Auto-post** (`auto`): scheduled cards are published immediately.

The Preview button is separate from the saved mode: it always queues a card and never posts. Schedules use the configured timezone, with Monday as day `0`. A slot is due from its start time through the next 29 minutes. GitHub's cron is best-effort and can be delayed; a delay longer than the window means that slot is skipped. Manual runs bypass the schedule check. `posting_paused` blocks scheduled and publish actions, while a manual dry run can still generate a preview.

The workflow's manual `dry_run` input defaults to `true`. The dashboard explicitly sends `false` when you choose a real run or publish action.

## Local development

Python 3.11 or newer is recommended.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Install Google Chrome. The renderer checks common Windows, macOS and Linux locations. If Chrome is elsewhere, set `CHROME_PATH` to the executable.

Create a local environment file from the example:

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in only the providers you use and leave the rest blank. `core.run` loads `.env` automatically for local runs, but real environment variables take precedence. `.env` is gitignored and is never used by GitHub Actions; use repository secrets there instead. Check what the loader can see without revealing values:

```powershell
.\.venv\Scripts\python.exe -m core.env
```

Run the offline tests:

```powershell
.\.venv\Scripts\python.exe -m tests.selftest_env
.\.venv\Scripts\python.exe -m tests.selftest_images
.\.venv\Scripts\python.exe -m tests.selftest_design
.\.venv\Scripts\python.exe -m tests.selftest_scheduler
.\.venv\Scripts\python.exe -m tests.selftest_post
.\.venv\Scripts\python.exe -m tests.selftest_pipeline
.\.venv\Scripts\python.exe -m tests.selftest_llm
```

Check the dashboard JavaScript syntax with Node:

```powershell
node --check docs/app.js
```

Local previews need internet access for news feeds. Without provider keys, the rule-based editor and generated background still work:

```powershell
.\.venv\Scripts\python.exe -m core.run --action generate_preview
```

On Windows, install `tzdata` if you want non-IST timezones to resolve locally:

```powershell
.\.venv\Scripts\python.exe -m pip install tzdata
```

## Checking a run

Open **Actions > NewsCard tick** and inspect the latest run. The dashboard's run sheet reads `data/status.json`, which is updated during the run and pushed back to the repo so the browser can follow progress.

`data/status.json` includes the current stage, provider and image choices, queue/card identifiers, errors and `ig_session` state. `data/queue.json` holds pending cards. `data/history.json` holds up to 60 recent records and 30 days of image usage.

Card images live in `docs/cards/` so Pages can serve them. Do not store private information on a card: Pages and the repository are public.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Dashboard returns 401 | Token expired, revoked or missing Contents access. Create a new fine-grained token and reconnect. |
| Dashboard returns 404 | Wrong owner/repo/branch, or the token cannot see the repository. |
| Dashboard cannot dispatch | Token needs Actions read/write access. |
| Pages shows a 404 | Pages is set to branch `main` and folder `/docs`, and the deployment finished. |
| "No post this time" | The slot is outside its 29-minute window, already ran, posting is paused, or the daily limit was reached. |
| "No fresh stories" | Feeds returned no recent, unique candidates. Wait, add topics, or check the run log. |
| Render failed | Chrome is missing or unreachable. Set `CHROME_PATH`; the fallback template is used only after validation. |
| Local keys not detected | Run `python -m core.env`. Process environment values override `.env`; remove the conflicting variable or restart the terminal. |
| Instagram challenge or expired session | Approve the login in the app, rerun `tools/get_session.py`, update `IG_SESSION_JSON`. Do not loop retries. |
| Instagram rate limit | Wait several hours. Publishing is not retried automatically. |
| Queue card image missing | Run **Regenerate** on the queue card, then approve again. |
| Scheduled workflow stopped | GitHub disables schedules in inactive repositories; re-enable the workflow. |
| Stale status on the dashboard | Pages/CDN and browser cache can lag. Pull to refresh or use Clear offline cache in Settings. |

## Cost and hosting notes

- GitHub Actions and Pages are free for public repositories within GitHub's current usage limits.
- Private repository usage is subject to the account's included Actions minutes and storage.
- LLM, Unsplash, Pixabay and Instagram usage is governed by those providers' own plans and terms.
- The pipeline commits generated card images to the repository, so repo size grows over time. History is capped at 60 records and unused card files older than 14 days are pruned.
- Scheduled GitHub Actions are not real-time guarantees. For exact posting times, trigger a manual run or use an external scheduler that dispatches the workflow.