# Test results

Tests from the brief, how each was run, and what happened. Screenshots are in
`docs/screenshots/`. Cloud tests were run on the AWS Academy Sandbox (us-east-1).

Two deployments:
- **Infrastructure run** (22 Oct 2026): stack built with a small synthetic snapshot,
  to test the cloud pieces before the real data was ready.
- **Full run** (22 Oct 2026, a new Sandbox session): stack built from scratch with the real data snapshot (results marked "full run").

## Data and code tests (automated, `pytest`, run in GitHub Actions on every push)

| Test | How | Result |
|---|---|---|
| Shares | `test_metrics.py::test_shares_sum_to_100_percent_per_product_month` | ✅ shares per product-month sum to 100% |
| HHI | `test_metrics.py::test_hhi_hand_worked_example` (60/30/10 → 3,600 + 900 + 100 = 4,600) and bounds 0–10,000 | ✅ matches by hand |
| Detector rules | `test_detector.py`: 5/3 point thresholds, value floor, gainer must be untariffed, confidence labels, trade-destruction label | ✅ |
| DiD | `test_detector.py::test_did_recovers_known_effect`: a planted −10 point effect | ✅ estimate within 0.5 points, t < −5 |
| Formatting (Feature 1) | `test_formatting.py`: no scientific notation; US$ m, %, points, HHI | ✅ |
| Saved analysis (Feature 3) | `test_storage.py`: save → reopen gives an identical analysis | ✅ |
| Snapshot integrity | `test_storage.py`: split into parts, restore, a tampered part is refused | ✅ |
| End to end | `test_pipeline_smoke.py`: synthetic raw data → every step → PostgreSQL (loaded twice: no duplicates) → every page; save, reopen, note, search, export, wipe, import, re-import | ✅ |
| Totals | `totals_check` table: our country sum against the Census "all countries" row, every month | ✅ **0.0% difference in all 140 months** (Jan 2015 – Aug 2026) |
| Known case: China → Vietnam | Detector on the 2018–19 Section 301 lists | ✅ 913 flags, China the loser in every one; **Vietnam the most frequent gainer** (100 products), then Mexico 91, Canada 83, India 71, Taiwan 53; 75% higher confidence |
| Known case: washing machines | Detector on the 2016 anti-dumping duties and the 2018 safeguard | ✅ 2016: China 75.1% → 1.7% of US imports of HS 8450.20, Vietnam 0% → 41.5%, Thailand 1.1% → 23.6% (diversion). 2018: no untariffed supplier could gain; total imports −32% (trade destruction, listed on the detector page) |
| DiD validation | `did_check.py` on the full data | ✅ Section 301 Lists 1 / 2 / 3 / 4A: β = −3.0 / −6.6 / −4.2 / −2.7 points, t = −3.9 / −5.6 / −5.6 / −4.1 |

## Cloud tests

| Test | How | Pass when | Result |
|---|---|---|---|
| **CloudFormation build** | Fresh Sandbox session → Create stack (RUNBOOK Part C) | App live from the ALB URL with no manual steps | ✅ Infrastructure run: `CREATE_COMPLETE` first attempt, ~20 min. **Full run (new session, new account): `CREATE_COMPLETE` first attempt in ~13 minutes** with the real snapshot: restore 144 MB in 25 s, load 11.2 million rows into RDS in 239 s, demo content loaded, EBS snapshot taken ([log](screenshots/batch-pipeline-cloudwatch-log.jpg)). |
| **Load balancing** | 12 and 20 calls to `/health` (instance ID and AZ in each answer) | Requests reach both instances | ✅ 6/6 and 10/10 split between `i-0d40…` (us-east-1a) and `i-0312…` (us-east-1b) |
| **Failover** | Terminated web server `i-0d406166747abccb4` (us-east-1a) while polling `/health` every 5 s | ALB marks it unhealthy; ASG replaces it; site stays up | ✅ 34 of 35 checks answered 200; one 5-second check timed out at the moment of termination. Requests moved to the 1b server, the group removed the dead instance and kept capacity with new instances in 1a; afterwards 20 `/health` calls split 10/10 between `i-0312…` (1b) and `i-0a4a…` (1a). |
| **Auto scaling** | Load on the ALB until the CPU alarm fires; stop; wait | ASG adds an instance, then removes it when load drops | ✅ **Full run (real data):** a 7-minute loop from CloudShell (in the same region), 16 parallel requests to the List 1 detector page: **5,856 requests, all HTTP 200**; average web CPU 73–76% each minute; the target-tracking `AlarmHigh` went to ALARM and desired capacity went **2 → 3** at 17:22:55 UTC, launching `i-0b5383…` ([screenshot](screenshots/scaling-real-data-cloudshell.jpg)); after the loop ended, `AlarmLow` fired and the group **terminated it at 17:40:05 UTC, back to 2** ([screenshot](screenshots/scaling-real-data-scale-in.jpg)). Infrastructure run: scale-out 2 → 3 at 14:54:30 UTC and **scale-in 3 → 2 at 15:11:55 UTC** ([screenshot](screenshots/scaling-and-security-cloudshell.jpg)). Load from a laptop in India could not pass ~11% CPU (network-bound), so run the load in-region. |
| **Security** | From CloudShell (outside the VPC), open a TCP connection to the RDS endpoint on 5432; RDS settings | RDS reachable only from the app security group | ✅ "Connection failed: RDS not reachable from outside the VPC"; `PubliclyAccessible=False`; console shows "Internet access gateway: Disabled" ([screenshot](screenshots/security-rds-no-public-access.jpg)); `DatabaseSecurityGroup` allows 5432 only from the web and batch security groups; the endpoint resolves only to a private VPC address. |
| **Restart** | End the lab and start a new session | App comes back with data intact | ✅ The Sandbox deletes everything at session end, so a restart is a rebuild. The full run rebuilt in a new session and account with all data (1,044 signals, 5,826 products, Jan 2015 – Aug 2026) and the demo History; saved work comes back with History → Export / Import (tested in `test_pipeline_smoke.py`). |
| **Cost** | See `docs/cost_estimate.md` | Within Sandbox credit | ≈ US$0.35 per 3-hour session. AWS Budgets is not on the Sandbox service list, so the US$10 alert is in the template but off by default. |

## Feature acceptance tests

| Test | Pass when | Result |
|---|---|---|
| Feature 1 · UI | Every number formatted; every signal has a summary and a working source link | ✅ Full run: 16 pages on the ALB, all HTTP 200, no raw `e+` values; source pages load in 0.5 s. Explorer chart page 1.5–1.8 s (target under 3 s). |
| Feature 2 · Comparison | Two suppliers, two products and two importers each compare correctly | ✅ Full run: suppliers (CN vs VN, washers), products (8450.20 vs 8450.11) and importers (US vs JP, 8471.30) each return chart and table together (1.1–1.2 s). |
| Feature 3 · Saved analysis | Save, terminate the web instance, reopen from History: identical | ✅ Full run: saved on `i-00761…` (us-east-1b), then terminated that instance; the replacement `i-00a3880…` served traffic after 171 s (30 of 31 health checks OK meanwhile) and reopened the analysis with both charts and its tables. |
| Feature 4 · Notes | A note added on one instance is visible after the ASG replaces it | ✅ Full run: note written on `i-0425…` (us-east-1a), shown on the saved analysis served by the replacement instance. |
| Feature 5 · Search | HS code + date range returns the right analyses in under 2 seconds | ✅ Full run: "HS 8450, last 6 months" returned 3 results (the two washer demo analyses and the test analysis) in **24 ms**. |
| Feature 6 · Scaling | Covered by the auto scaling test above | ✅ |

## Issues found by testing, and fixed

| Found by | Problem | Fix |
|---|---|---|
| CI (Python 3.11) | The wheel bundle missed `typing-extensions`, which psycopg needs below Python 3.13 (pip skipped it because the bundle was built on 3.14) | Pinned it explicitly; rebuilt the bundle |
| Long downloads | A network read timeout ended the Census and Comtrade jobs | Both now retry dropped connections, and resume where they stopped |
| Smoke test | `text_pattern_ops` indexes don't accept `char(n)` columns | Code columns are `varchar` |
| Infrastructure run | CPU metrics every 5 minutes make the scaling demo slow | Detailed (1-minute) monitoring on the web launch template |
| Full run, overload test | 30 clients on the all-events detector (several CPU-seconds per request) queued requests past 60 s; `/health` shares the gunicorn workers, so ALB health checks timed out and the group replaced both servers | Load test now uses normal pages with 10 clients; 3 gunicorn workers per server; health check timeout 10 s and 5 failures (75 s) before a server is unhealthy |
| Full run, stack update | Changing `SnapshotUrl` with Update stack did not reload data: EC2 runs user data only on first boot | RUNBOOK troubleshooting entry; `batch_run.sh snapshot --force` reloads in place |
