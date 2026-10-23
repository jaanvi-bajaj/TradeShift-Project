# TradeShift: the simple walkthrough

This guide is for someone who has never used AWS. Do every step in order. Don't skip any.
After each step there is a **✅ You should see** line. If you don't see it, stop and read
**"If something goes wrong"** at the end.

It takes about **30 minutes**. Most of that is waiting.

---

## What is TradeShift? (read this once)

- When the US put taxes (tariffs) on goods from a country, people bought those goods from
  **other** countries instead.
- TradeShift is a website that **finds those switches** for you. Example: "China sold 75% of
  big washing machines to the US, then 2%. Vietnam went from 0% to 41%."
- The website runs on **AWS**, which is Amazon's computers that you rent over the internet.
- We built it so that **one button** creates everything on AWS: the website, the database
  and the storage. That button is called **CloudFormation**.

---

## Part 1: Turn on the AWS sandbox

The "sandbox" is a free practice AWS account from the course. It **switches itself off after
3 hours and deletes everything**. That is normal; you just start again from Step 1 next time.

**Step 1.** Open the AWS Academy course page in your browser. Click **Modules**, then click
**Sandbox Environment**.

✅ You should see a page with text on the left and a black box on the right.

**Step 2.** At the top right, click the button **Start Lab**.

✅ A small circle starts spinning next to "Start Lab". Wait. When it stops, the timer next to
"End Lab" shows about **3:00**. That means you have 3 hours.

**Step 3.** Click the button **AWS** (top right, next to Start Lab).

✅ A new tab opens with the AWS website. At the top right it says **N. Virginia**.

> If the new tab says "Credentials do not match current AWS Account": click the word
> **here** on that page, close that tab, and click **AWS** again.
>
> If it does not say N. Virginia: click the region name at the top right and choose
> **US East (N. Virginia)**.

---

## Part 2: Build everything with one file

**Step 4.** In the AWS tab, click the search box at the very top. Type **CloudFormation** and
press Enter. Click **CloudFormation**.

✅ You see a page titled "Stacks".

**Step 5.** Click the orange button **Create stack**. If a small menu opens, click
**With new resources (standard)**.

**Step 6.** Under "Specify template", click **Upload a template file**. Click **Choose file**.
Find and pick this file on your computer:

`TradeShift-Project / infra / cloudformation / tradeshift.yaml`

Then click **Next** (bottom right).

✅ A long form opens with many boxes.

**Step 7.** Fill in only these four boxes. Leave every other box exactly as it is.

| Box name | What to type |
|---|---|
| **Stack name** (at the top) | `tradeshift` |
| **WheelhouseSha256** | `f2be85195b2193585db037c7035d7873d932621d2fa553cbdbefc5a3f0b09ab0` |
| **SnapshotSha256** | `2ba1c3eb046d8b923eb71a2104961b2c0578c7dd78f4f7a73d59e807eaa44fc8` |
| **DBPassword** | Make up a password with **only letters and numbers**, at least 8 of them, e.g. `Jaanvi2003`. **No `@`, no spaces, no symbols.** |

> Tip: copy and paste the two long codes. Don't type them by hand.

**Step 8.** Scroll down and click **Next**. On the next page, don't change anything; click
**Next** again. On the last page, scroll down and click **Submit**.

✅ You see a page called **tradeshift** with the status **CREATE_IN_PROGRESS** (blue).

---

## Part 3: Wait for it to finish (about 13 minutes)

**Step 9.** Click the tab **Events**. Every 2 minutes, click the round **refresh** arrow on the
right side of the page.

✅ New lines keep appearing. This is AWS building the parts one by one. The slowest part is
the **Database** (about 8 minutes). Just wait.

**Step 10.** Keep refreshing until the status at the top says **CREATE_COMPLETE** (green).

✅ Green **CREATE_COMPLETE**. Everything is built and the data is loaded.

---

## Part 4: Open the website

**Step 11.** Click the tab **Outputs**.

✅ You see a small table. The important line is **AppUrl**. It looks like
`http://trades-LoadB-xxxxxxxx.us-east-1.elb.amazonaws.com`.

**Step 12.** Click the **AppUrl** link. If your work laptop blocks it, open the same link in
**Safari** or on **your phone**.

✅ The TradeShift home page opens. It says **1,044 flagged product shifts** and
**Jan 2015 – Aug 2026**.

**Step 13.** Scroll to the very bottom of the page. It says "Served by **i-xxxx** in
**us-east-1a**" (or 1b). Press refresh a few times.

✅ The **i-xxxx** code and the **1a / 1b** change. That proves two computers share the work.

---

## Part 5: Try every page of the website

Click each word in the black bar at the top of the website.

| Click | Do this | ✅ You should see |
|---|---|---|
| **Explorer** | Type `845020` in the Product box, click **Apply** | A chart of washing machines. China's line falls off a cliff in mid-2016. |
| **Detector** | Choose any event, move a slider, click **Run detector** | A list of products where trade moved. The number changes when you move the slider. |
| **Concentration** | Look at the chart | How many countries a product is bought from, before and after each tariff |
| **Top movers** | Just look | The 20 biggest switches, each with one simple sentence |
| **Singapore lens** | Just look | Singapore's exports to the US, with a note that it doesn't prove cheating |
| **Compare** | Type `CN` in A and `VN` in B, click **Compare** | China and Vietnam side by side |
| **History** | Click any title | A saved page opens, looking exactly like when it was saved |
| **Notes** | Go back to any page, write in the Notes box, click **Add note** | Your note appears on that page and on the Notes page |
| **Search** | Type `8450`, click **Last 6 months** | Saved items about washing machines, and the time it took (a few ms) |

To save your own page: go to the bottom of any page, click **Save analysis**. It now appears
in **History**.

---

## Part 6: Look at what AWS built (for the presentation)

Go back to the **AWS tab**. Use the search box at the top each time.

| Search for | Click | ✅ You should see | What it means |
|---|---|---|---|
| **EC2** | **Instances** (left menu) | `tradeshift-batch` and two `tradeshift-web` | One computer loads the data; two run the website. (Bastion Host and Lab Instance belong to the course; ignore them.) |
| **EC2** | **Auto Scaling Groups** → the tradeshift one → **Activity** tab | A list of "Launching a new EC2 instance" lines | AWS adds or removes website computers by itself |
| **EC2** | **Target Groups** → the tradeshift one → **Targets** tab | Two lines saying **healthy** | The load balancer checks both computers are alive |
| **RDS** | **Databases** → the tradeshift one → **Connectivity & security** | "Internet access gateway: **Disabled**" | The database can't be reached from the internet. Safe. |
| **S3** | The bucket starting with `tradeshift-databucket` | Folders `processed/` and `analyses/` | Where the data files and saved pages are kept |
| **CloudWatch** | **Dashboards** → `tradeshift-dashboard` | Six small charts | Live health of the website |
| **CloudWatch** | **Alarms** | A list of alarms, most **OK** | Alerts if something goes wrong |
| **CloudWatch** | **Log groups** → `/tradeshift/tradeshift/batch` → the one ending in `pipeline` | Lines like "Loaded trade_monthly: 11164137 rows" | Proof the data was loaded |

---

## Part 7: Show the three "wow" tests (optional, for the demo)

**Test A: a computer breaks, the site keeps working**

1. **EC2 → Instances**. Tick **one** `tradeshift-web`. Click **Instance state** → **Terminate
   (delete) instance** → **Terminate (delete)**.
2. Keep using the website. It still works.
3. Wait 3 minutes and refresh the Instances page.

✅ A **new** `tradeshift-web` has appeared by itself. Your saved pages and notes are still there.

**Test B: lots of visitors, AWS adds a computer**

1. In the AWS tab, click the small **CloudShell** icon (a `>_` box) at the top. A black window opens.
2. Copy this line, but replace `PUT-APPURL-HERE` with your **AppUrl** from Step 11:

   ```
   U=PUT-APPURL-HERE; end=$((SECONDS+420)); while [ $SECONDS -lt $end ]; do seq 16 | xargs -P 16 -I{} curl -s -o /dev/null "$U/detector?event_id=S301_L1"; done
   ```

3. Paste it into the black window and press Enter. It runs for 7 minutes.
4. Go to **EC2 → Auto Scaling Groups → tradeshift → Activity**.

✅ After about 5 minutes: "increasing the capacity from **2 to 3**". About 15 minutes after the
7 minutes end: it goes back to 2.

**Test C: the database is locked**

In the CloudShell window, paste this (replace the address with your **RdsEndpoint** from Step 11):

```
timeout 8 bash -c '</dev/tcp/PUT-RDSENDPOINT-HERE/5432' && echo OPEN || echo BLOCKED
```

✅ It prints **BLOCKED**. Nobody outside can reach the database. That's good.

---

## Part 8: Before you stop

**Step 14.** On the website, click **History** → **Export all analyses and notes (.zip)**.
Save the file on your laptop.

> The sandbox deletes everything when it ends. Next time, after Step 13, go to **History** →
> **Choose file** → pick that .zip → **Import**, and your saved pages come back.

**Step 15.** Go back to the course tab and click **End Lab**.

✅ Done. Next time, start again from **Step 1**.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| Red text about **DBPassword** | Use only letters and numbers, at least 8. No `@`, no spaces. |
| Status becomes **ROLLBACK** or **FAILED** (red) | Click **Delete** on the stack, wait until it's gone, and start again at Step 4. Check the two long codes were pasted correctly. |
| Website says "Trade data is still loading" | Wait 2 minutes and refresh. |
| Website link doesn't open on your laptop | Your work browser blocks it. Use Safari or your phone. |
| Timer reached 0:00 | Everything was deleted. Start again at Step 1. |
| "Credentials do not match" | Click **here** on that page, close the tab, click **AWS** again. |
