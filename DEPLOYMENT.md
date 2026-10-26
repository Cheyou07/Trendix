# Publish the scanner and retain seven days of daily results

The repository now includes a deployable Docker image, a Render Blueprint,
MongoDB history, a public history screen, and a GitHub Actions scheduler.
No account credentials are in these files. Existing deployments can use the
upgrade steps below without changing MongoDB credentials or GitHub secrets.

## Upgrade an existing deployment after the stuck-scan fix

1. Deploy the latest `main` commit in Render (or wait for automatic deployment).
   The restart clears the old stuck in-memory scan.
2. Keep **one Uvicorn worker and one Render instance**. The app now starts at most
   one disposable scan process alongside that web worker.
3. Keep the existing `SCANNER_URL` and `CRON_SECRET` GitHub secrets unchanged.
   The updated workflow installs Python dependencies, computes on GitHub's runner,
   and uploads results. No MongoDB URI is needed in GitHub.
4. Cancel any older still-running **Daily setup snapshots** workflow, then run
   the latest workflow after Render finishes deploying.
5. Run a NIFTYBANK setup from the website, then another setup. Progress shows the
   stock count. `/api/scanner/status` reports activity, queued scans and the deadline;
   `/api/health` includes the deployed commit when Render supplies it.

The previous implementation could leave Yahoo's shared batch downloader waiting
indefinitely after an overlapping chart request. Neither the scanner nor the
shared daily/interactive queue had a server deadline. The new downloader uses
independent per-ticker histories, and a hard process timeout releases the slot even
if a data request hangs. The old scheduler endpoint returns HTTP 410 and cannot
occupy the interactive queue.

## Recommended first deployment

| Service | Purpose | Starting tier |
| --- | --- | --- |
| Render | Serves React and the Python API together at one HTTPS URL | Free web service |
| MongoDB Atlas | Stores compressed daily results independently of server restarts | Free cluster |
| GitHub Actions | Computes daily scans and uploads snapshots | Standard Linux runner, subject to account allowance |

Vercel is optional. It hosts the frontend if desired; MongoDB is the actual
database. Keeping both frontend and backend on Render initially avoids a second
deployment and cross-origin configuration.

### 1. Put this folder in a GitHub repository

Use your existing repository or create one, then push this project, including
`.github/workflows/daily-snapshot.yml`, `Dockerfile`, and `render.yaml`.
A private repository is fine; public website access does not require public source.

The included `.gitignore` excludes `venv`, `node_modules`, generated files, cached
market data, and `.env` secrets. Keep `frontend/package-lock.json` and all nine
files under `backend/app/setups/` in the repository.

### 2. Create MongoDB Atlas storage

1. Create an Atlas project and choose a **Free** cluster.
2. Create a database user with `readWrite` access to the `nifty_scanner` database.
   This is a database user, separate from your Atlas login.
3. Choose **Connect → Drivers → Python**, and copy the `mongodb+srv://...` URI.
   Substitute your database username and password, URL-encoding reserved characters.
4. You will add Render's outbound address ranges to Atlas **Network Access** after
   creating the Render service. All ranges shown for the service are needed.
   See [Render outbound IP addresses](https://render.com/docs/outbound-ip-addresses).

Set the URI only in Render's environment settings. Do not commit it or place it
in any `VITE_` variable: frontend variables are public browser code.
The app creates its collection and indexes on first history use.

### 3. Deploy on Render

1. In Render, create a **Blueprint**, connect the GitHub repository, and select
   the branch containing `render.yaml`.
2. Confirm that the web service uses the **Free** plan. Keep the repository root
   as the build context; do not set the service root to `backend/`.
3. Supply `MONGODB_URI` when prompted. The Blueprint sets `MONGODB_DATABASE` to
   `nifty_scanner`, includes all five indexes in `SNAPSHOT_INDEXES`, and generates
   a random `CRON_SECRET`.
4. Deploy. The Docker build installs the frontend dependencies, builds React,
   installs Python dependencies, and starts FastAPI with one worker.
5. Add the service's outbound IP ranges to Atlas Network Access as described above.
6. Open Render's assigned URL, such as `https://YOUR-SERVICE.onrender.com`.
   That is the single link to share. The example is a placeholder, not a live URL.

If Blueprint creation is unavailable, create a Docker Web Service manually with
the same environment variables and Free plan. Set health check path `/api/health`.
Generate a long random `CRON_SECRET` in your password manager for that path.

**Use exactly one service instance and one Uvicorn worker.** The job queue is
in memory. Multiple processes would not share polling state or concurrency limits.
Restarting the service loses in-progress jobs, but never the saved MongoDB history.

### 4. Turn on automatic daily runs

In GitHub, open **Settings → Secrets and variables → Actions → Repository secrets**:

| Secret | Value |
| --- | --- |
| `SCANNER_URL` | Your Render HTTPS URL without `/api` |
| `CRON_SECRET` | The exact `CRON_SECRET` from Render's environment settings |

The workflow must be on the repository's default branch, and GitHub Actions must
be enabled. Under **Actions → Daily setup snapshots → Run workflow**, trigger a
first run manually. Wait for the job to succeed, then open **Daily history (7 days)**
in the website and choose an index/setup.

The schedule is **16:47 IST every calendar day** (`17 11 * * *` in UTC), after the
regular market close. Weekends and holidays still get a snapshot using the latest
available candles; each stock's saved breakdown shows `data_as_of`.
GitHub schedules can run late or be dropped under load, and public repositories'
schedules are disabled after 60 days without activity. Monitor workflow failures;
there is no guaranteed daily execution or historical backfill. A manual retry on
the same day is safe. See [GitHub schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

The workflow reads an authenticated daily plan, fetches prices and computes all
setups on the GitHub runner, then uploads each missing snapshot to Render.
It never enters the visitor scan queue. MongoDB credentials stay only on Render;
GitHub needs neither the database URI nor direct Atlas network access. Uploads
retry transient failures. A failed daily scan fails the workflow visibly.

## Exactly what gets stored

- Every configured index: NIFTY50, NIFTYBANK, NIFTY100, NIFTY200, NIFTY500.
- Every registered setup: currently nine.
- One document per **India date + index + setup**, shared by all visitors.
- All evaluated stock scores and condition breakdowns, including nonmatches.
- Capture time, latest candle date per stock, evaluated/configured symbol counts,
  missing symbols, and an indication of whether all configured symbols were evaluated.
- Gzip-compressed result payloads to reduce storage. No historical chart candles,
  download CSVs, accounts, or per-visitor run history are persisted.

The first saved scheduled result for a date/index/setup is preserved. Repeated
requests do not overwrite it or extend its expiry. Partial market-data runs are
saved with missing symbols listed; rerunning that day will not replace them.
If an index has no usable stock data, it is not saved as a successful empty run.
If a job fails midway through writing, retrying fills missing snapshots without
duplicating those already saved.

There can be up to **45 snapshots per day and 315 visible snapshots across seven
calendar dates**. Results are public and have no user-specific information.
Stocks shared across indexes are fetched and evaluated once per daily run, then
included in each relevant index's snapshot.

Retention uses today plus the previous six India-calendar dates. For example,
an October 26 snapshot expires at **00:00 IST on November 2**, regardless of what
time it was saved. A unique MongoDB compound index prevents duplicates, and a
TTL index on `expires_at` removes expired records progressively. MongoDB's physical
deletion is asynchronous; API queries also filter expired records so the website
never shows history past the cutoff. See [MongoDB TTL indexes](https://www.mongodb.com/docs/manual/core/index-ttl/).

## What visitors can do

Visitors open the URL and run a single setup or all setups against any available
index. No local installation or account is required. These interactive runs do
not overwrite the scheduled history.

Scans use `POST /api/runs` and `GET /api/runs/{job_id}` so the browser waits through
short polling requests. Identical jobs reuse results for up to five minutes;
one interactive scan runs at a time, with two additional distinct scans allowed
in a FIFO queue. There is no global cooldown. The browser shows queue position
and actual stock progress; it retries admission if the queue is full.
Each scan runs in a disposable process, terminated after at most ten minutes
(`SCAN_TIMEOUT_SECONDS` can lower the limit, between 30 and 600 seconds).
Failed scans release the slot immediately and can be retried. Price data is
cached locally for five minutes to reduce repeated downloads across setups.
Visitors can stop waiting; already-started shared server work continues within
its deadline. Admission waits and processing share a 30-minute browser deadline.
Actual scan failures are displayed without silently rerunning them. The previous
synchronous `/api/scan` and `/api/scan-all` routes have been
replaced; external API clients must migrate to the job endpoints.

## Free-tier and data limitations

This is an initial beta configuration, not an availability guarantee:

- Render Free sleeps after 15 idle minutes, may take about a minute to wake,
  and has usage limits. Local files disappear on restart; Atlas holds the history.
  Render explicitly recommends free instances for testing/hobby workloads rather
  than production. See [Render free hosting](https://render.com/docs/free).
- Atlas Free has 512 MB of storage including indexes. Compression and seven-day
  expiry should keep this small, but actual payload size and database usage must
  be measured after deployment. See [Atlas limits](https://www.mongodb.com/docs/atlas/reference/free-shared-limitations/).
- Standard GitHub-hosted runners are free for public repositories; private
  repositories have account-specific included allowances. Computing snapshots
  consumes runner time. See [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
- Yahoo/NSE availability from the hosting region must be verified with a real
  deployed scan. Cloud IP restrictions, rate limits, or free-service memory/CPU
  limits may cause failures, particularly with all five indexes.
- Existing `universe.py` uses a manually maintained, incomplete NIFTY50 list and
  a static NIFTYBANK list. Larger indexes can silently fall back to smaller lists
  when NSE is unavailable. The saved completeness flag measures fetching against
  the configured list, **not** whether that list is the official current index.
  Refresh the index data/provider before relying on full market coverage.
- The yfinance project states Yahoo's API is intended for personal use. Confirm
  your data rights for public redistribution, or use a provider licensed for your
  intended audience. See [yfinance's own notice](https://github.com/ranaroussi/yfinance#readme).

For more traffic, move to a persistent task queue, shared caching/rate limiting,
and appropriately sized compute. Do not increase Uvicorn workers on this version.

## Optional: frontend on Vercel

Deploy the backend on Render as above. Import the GitHub repository into Vercel,
choose root directory `frontend`, framework Vite, build command `npm run build`,
and output directory `dist`. Add `VITE_API_BASE_URL` with
`https://YOUR-SERVICE.onrender.com/api` before building.

Set Render's `CORS_ORIGINS` to the exact frontend origin, such as
`https://YOUR-PROJECT.vercel.app`. Multiple allowed origins may be comma-separated.
Redeploy after changing these settings and share the frontend URL instead.
Vercel's Hobby plan is restricted to personal, noncommercial use; review its
[plan terms](https://vercel.com/docs/plans/hobby) for your intended audience.

## Local checks

From `backend/`:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

From `frontend/`: `npm ci` then `npm run build`.

The existing run scripts still support local development. Environment variables
must be set in your shell or hosting dashboard; `.env.example` is documentation,
and the backend does not automatically load `.env` files. Live scans work without
MongoDB; history reports an explicit unconfigured message until `MONGODB_URI` is set.

After deployment, verify `/api/health`, open the website, run a NIFTY50 scan, run
the daily workflow manually, and inspect saved history for all indexes/setups.
Trigger the workflow again that day and confirm snapshot counts do not increase.
Test a second browser and mobile layout. Watch Atlas storage and Render memory
during the first full scan. No live database, cloud scan, browser rendering, or
Docker image runtime has been verified by the local automated tests.

## Later: Play Store and App Store

The hosted API can remain the backend for mobile apps. A possible next step is
packaging the React frontend with [Capacitor](https://capacitorjs.com/docs), followed
by mobile UX work, native builds, signing, store metadata, and store review.
Publishing a website does not itself publish an app to either store. This change
does not create native app projects or store submissions.
