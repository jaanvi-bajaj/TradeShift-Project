# RUNBOOK: deploy TradeShift on the AWS Academy Sandbox

Follow the steps in order. Each step says what you should see; if you don't see it, stop
and check **Troubleshooting** at the end. A full build takes about 20 minutes.

> **The Sandbox deletes everything when the session ends.** You rebuild with this runbook
> every session; the data comes back by itself from the snapshot. Your own saved
> analyses and notes do not, so **export them before you end the lab** (Part E).

---

## Part A: once only (already done; for reference)

You only need this if you rebuild the data or the package bundle.

1. **Package bundle:** `bash scripts/build_wheelhouse.sh`, then upload
   `dist/wheelhouse-py311-x86_64.tar.gz` (+ `.sha256`) to the GitHub release `deps-py311-v1`.
2. **Data:** on a laptop or Codespaces, never in the Sandbox (it would waste the Comtrade quota):
   `python -m batch.run_pipeline`, then
   `python -m batch.snapshot export processed` and `python -m batch.snapshot export raw`.
   Upload everything in `dist/` named `tradeshift-processed*` and `tradeshift-raw*` to the
   GitHub release `data-v1`. Note the manifest's SHA-256 (printed at the end) in the
   release notes.

**Check:** the `data-v1` release lists `tradeshift-processed.json` and its `.partNN` files.

---

## Part B: start the Sandbox

1. Open the AWS Academy course → **Modules** → **Sandbox Environment** (Vocareum).
   **You see:** the Sandbox README on the left and a terminal on the right.
2. Click **Start Lab** (top right). Wait until the circle next to it disappears and the
   timer shows about **3:00**.
   **You see:** a "Start Lab" panel with `Lab status: ready` (close it with **X**).
3. Click **AWS** (top right).
   **You see:** the AWS console in a new tab, region **N. Virginia (us-east-1)** at the top right.
   If not, choose **us-east-1** from the region menu; other regions are blocked.

---

## Part C: create the stack

1. Search **CloudFormation** in the console search bar and open it. Click **Create stack** →
   **With new resources (standard)**.
2. Under *Specify template* choose **Upload a template file** → **Choose file** → pick
   `infra/cloudformation/tradeshift.yaml` from the repo. Click **Next**.
   **You see:** an S3 URL appears under the file name (CloudFormation stored your template).
3. **Stack name:** `tradeshift`.
4. **Parameters.** Leave every default except:

   | Parameter | What to enter |
   |---|---|
   | `WheelhouseSha256` | the SHA-256 in the `deps-py311-v1` release notes |
   | `SnapshotUrl` | leave the default (`.../data-v1/tradeshift-processed.json`) |
   | `SnapshotSha256` | the manifest SHA-256 in the `data-v1` release notes |
   | `DBPassword` | **type your own**: 8+ letters and digits only (RDS rejects `@ / "` and spaces). Not stored anywhere. |
   | `SshCidr` | only if you want SSH to the batch server: your IP as `x.x.x.x/32` (search "what is my IP") |
   | `AlertEmail` | optional: your email for alarm notifications |

   Leave `CensusApiKey` and `ComtradeApiKey` **empty**. Snapshot mode doesn't call the data APIs.
   Leave `EnableBudget` as **false**: AWS Budgets isn't on the Sandbox's service list.
5. Click **Next**. On *Configure stack options* change nothing. Click **Next**.
6. On *Review and create* click **Submit**.
   **You see:** the stack page with status `CREATE_IN_PROGRESS`.
7. Open the **Events** tab and press the refresh button every few minutes. Rough timings:
   - 0–2 min: VPC, subnets, security groups, S3 bucket, log groups → `CREATE_COMPLETE`
   - 2–12 min: `Database` (RDS) `CREATE_IN_PROGRESS`, the slowest part
   - 12–20 min: `BatchServer` and `WebAutoScalingGroup` wait for their servers to report in.
     The batch server restores the data snapshot into S3 and loads RDS before it reports.
8. **Check:** the stack status is **`CREATE_COMPLETE`** (green).

### What each section of the template builds (for the presentation)

| Section | Resources | In plain words |
|---|---|---|
| Network | VPC, 2 public + 2 private subnets in 2 AZs, internet gateway, route tables, S3 endpoint | Our own private network across two data centres. Only the public subnets can reach the internet. |
| Security | 4 security groups | Firewalls: internet → load balancer only; load balancer → web servers only; web + batch → database only; SSH to the batch server from one IP only. |
| Storage | S3 bucket with a lifecycle rule | Raw API files, processed tables and saved analyses. Raw files move to a cheaper class after 30 days. Kept if the stack is deleted. |
| Database | RDS PostgreSQL in the private subnets | Trade data, signals, notes and analysis metadata. No public address. Daily backups; final snapshot on delete. |
| Compute | Batch EC2 + 20 GB EBS data volume | Restores the data snapshot (or downloads from the APIs), loads RDS, then snapshots its EBS volume. |
| Scaling | Launch template, Auto Scaling Group (2–3), ALB, target group, CPU policy | Identical stateless web servers behind a load balancer; a third is added when average CPU passes 50%. |
| Monitoring | Log groups, 5 alarms, SNS topic, dashboard | Logs from every server, alerts for high CPU / unhealthy servers / errors / database load, and one-screen dashboard. |

---

## Part D: check it works

1. Stack → **Outputs** tab. Click **AppUrl** (`http://tradeshift-...elb.amazonaws.com`).
   **You see:** the TradeShift home page with headline numbers and the biggest shifts.
   The footer says *Served by i-0... in us-east-1a* (or b).
2. Refresh the page a few times.
   **You see:** the instance ID in the footer changes between two values, in two AZs
   (load balancing works).
3. Open **Detector**, choose *Section 301 List 1*, move a slider and click **Run detector**.
   **You see:** the number of flagged products changes.
4. Open **History**.
   **You see:** the demo analyses. Open one; it shows the same charts and tables as when it was saved.
5. CloudWatch → **Dashboards** → `tradeshift-dashboard`.
   **You see:** requests, 2 healthy hosts, CPU, RDS connections.

The cloud tests (scaling, failover, security, restart) are in `docs/testing.md`.

**Scaling demo (Feature 6):** open **CloudShell** (icon at the top of the console) and paste
`U=<AppUrl>; end=$((SECONDS+420)); while [ $SECONDS -lt $end ]; do seq 16 | xargs -P 16 -I{} curl -s -o /dev/null "$U/detector?event_id=S301_L1"; done`
**You see:** within 3–5 minutes the CloudWatch dashboard shows CPU above 50% and the Auto
Scaling group's **Activity** tab shows "increasing the capacity from 2 to 3". About 15 minutes
after the loop ends, it shows a termination back to 2.

---

## Part E: before you end the lab

1. In the app, open **History** → **Export all analyses and notes (.zip)**. Save the file on your laptop.
2. (Optional) CloudFormation → select `tradeshift` → **Delete**. The Sandbox also deletes
   everything when the timer reaches 0:00.
3. Click **End Lab** in Vocareum.

Next session: Part B → Part C → History → **Import** your zip.

---

## Troubleshooting

| What you see | Why, and what to do |
|---|---|
| `Parameter DBPassword failed to satisfy constraint` | Only letters and digits, 8–41 characters. |
| `BatchServer` → `CREATE_FAILED`, "received 1 FAILURE signal" | The pipeline failed. EC2 → the `tradeshift-batch` instance → **Actions → Monitor and troubleshoot → Get system log**, or CloudWatch → Log groups → `/tradeshift/tradeshift/batch`. A wrong `SnapshotSha256` shows `checksum mismatch`. |
| `WebAutoScalingGroup` → "Received 0 SUCCESS signal(s) out of 2" | The web servers didn't start the app. CloudWatch → `/tradeshift/tradeshift/web` → `<instance>/bootstrap`. A wrong `WheelhouseSha256` shows a `sha256sum` failure. |
| App shows "Trade data is still loading" | The batch server is still loading RDS; wait a few minutes. |
| Stack stuck for 40 minutes, then rolls back | A server could not reach GitHub. Check the release URLs still work in a browser. |
| `CREATE_FAILED` on `CostBudget` | Budgets isn't allowed; set `EnableBudget=false`. |
| Region errors everywhere | Switch the console to **us-east-1**. |
| Changed `SnapshotUrl` with **Update stack**, but the app still shows the old data | Changing user data does not replace the batch server: CloudFormation restarts it, and EC2 runs user data only on first boot. Either delete and recreate the stack, or reload in place: EC2 → `tradeshift-batch` → **Connect → Session Manager**, then run `sudo sed -i 's#^SNAPSHOT_URL=.*#SNAPSHOT_URL=<new manifest URL>#; s#^SNAPSHOT_SHA256=.*#SNAPSHOT_SHA256=<new sha>#' /etc/tradeshift.env && cd /opt/tradeshift && sudo git pull && sudo bash infra/scripts/batch_run.sh snapshot --force` |
