# Design choices, and why

Each choice below is one the rubric's "implementation choices" question can be about.
Every group member should be able to give the one-line answer.

## Cloud architecture

| Choice | One-line answer | More detail |
|---|---|---|
| **EC2 for the batch job, not Lambda** | A full download runs for hours, and Lambda stops at 15 minutes. | One Census month takes the API about 4 minutes to build. A decade is 128 months, and Comtrade's quota spreads its part over days. |
| **Not Elastic Beanstalk** | Beanstalk hides the VPC, subnets and scaling setup we want to show and explain. | With CloudFormation every security group, subnet and scaling rule is visible in one file. |
| **CloudFormation, not Terraform** | The rubric names CloudFormation for "Excellent", and the Sandbox supports it natively. | "Create stack" builds everything; "Delete stack" removes it. |
| **One stack, sections in order** | One click builds a fresh Sandbox in under 20 minutes. | network → security → storage → database → compute → scaling → monitoring. |
| **Two AZs, public + private subnets** | The load balancer and web servers span two AZs, so losing one AZ keeps the site up. RDS sits in private subnets with no route to the internet. | Week 3 (global infrastructure) and Week 5 (VPC). |
| **No NAT Gateway** | It costs money every hour, and we don't need it. | Web and batch servers sit in public subnets, but their security groups only accept the ALB (web) or one SSH address (batch). |
| **ALB + Auto Scaling Group, 2–3 web servers** | The ALB spreads requests across servers in both AZs; the group adds a server when average CPU passes 50%. | The minimum is 2, not 1, so the load-balancing test always sees two instances and each AZ has one. |
| **Stateless web servers** | Any server can be added or removed at any time without losing anything. | Data is in RDS, saved analyses in S3, notes in RDS. Nothing is written to the web server's disk. |
| **S3 for saved analyses, not EBS** | An EBS volume attaches to one instance, so with auto scaling each server would see different files. S3 is shared by all of them. | EBS is still used where it fits: the batch server's working files (Week 7). |
| **EBS data volume on the batch server** | A decade of trade data doesn't fit in a small server's memory, so the job works chapter by chapter on disk. | It is snapshotted after each pipeline run. |
| **RDS PostgreSQL** | Relational data (products, suppliers, months), metadata search with indexes, and managed backups. | Week 8. Single-AZ because the Sandbox doesn't allow Multi-AZ. |
| **LabRole / LabInstanceProfile** | The Sandbox doesn't allow creating IAM roles. | Every instance uses the pre-made instance profile. |
| **Secrets as NoEcho parameters** | The repo is public, so no password or key can be in Git. | Secrets Manager isn't available in the Sandbox. |
| **IMDSv2 required on every instance** | Blocks the common metadata-stealing attack (SSRF) at no cost. | `MetadataOptions: HttpTokens: required`. |
| **Packages installed offline from a release bundle** | Every server gets exactly the same pinned versions, and a deploy doesn't depend on a package registry being up. | `scripts/build_wheelhouse.sh`; CI installs from the same bundle. |
| **Snapshot on a GitHub release** | The Sandbox deletes everything at session end. The processed data is published once, and every new stack restores it in minutes without calling any data API. | Split into parts under 95 MB with a SHA-256 per part, which the batch server checks. |
| **Downloads run outside the Sandbox** | Running them in each session would waste the 500-a-day Comtrade quota and hours of download. | Run once in Codespaces or on a laptop, then publish raw and processed snapshots. |
| **Export / Import of saved work** | Saved analyses and notes would otherwise be lost every session. | History page buttons; the snapshot also carries demo analyses and notes. |

## Data and economics

| Choice | One-line answer |
|---|---|
| **US Census for the main series** | Monthly, by country of origin and HS6, from 2016. The importer's own records are the most direct measure of where its imports come from. |
| **Japan as the second importer** | Large, reports monthly HS6 data to Comtrade reliably, and wasn't the target of the 2018 US tariffs, so it's a natural comparison. |
| **Net weight from Comtrade for the quantity check** | Census has no quantities at HS6. Value shares can move with prices alone; if weight shares move the same way, the shift is real goods moving. |
| **12 months before vs 12 months after, skipping 2 months** | Twelve months removes seasonality, and the skipped months leave out goods already in transit when the tariff hit. |
| **Pooled window shares** | The window share is total value from a supplier divided by total imports in the window, which is the value-weighted average of the monthly shares. |
| **Thresholds 5 and 3 points, US$10m floor** | From our proposal. They're adjustable with sliders, and the floor removes small, noisy lines. |
| **Several tariffed suppliers per event** | Section 232 hit many countries with exemptions, so each event lists who was tariffed and who was exempt. |
| **Value redirected = min(loss, gain) × average annual imports** | Only the share that moved between the pair counts as redirected. |
| **Diversion vs trade destruction** | If total imports fell 25% or more, part of the lost share left the market instead of going to another supplier. |
| **Difference-in-differences per tariff list** | Compares tariffed products with untariffed products in the same HS4 headings, with product and month fixed effects and errors clustered by product. It validates the detector as a whole; it isn't a claim about any single product. |
| **HS revisions (2017, 2022)** | Codes that start or stop exactly at a revision are flagged; they're marked in the detector and left out of the DiD check. |
| **Singapore re-exports estimated** | No free source splits Singapore's re-exports by HS6. We estimate them as Singapore's exports to the US minus US imports of Singapore-origin goods, and check the total against SingStat's official figure. |
| **"Hub growth, not transshipment"** | US data records country of origin, so goods passing through Singapore are still counted under where they were made. |

## Limits we state up front

- Shifts in share aren't proof of causation; the DiD check is the validation.
- We compute no prices or costs, so we make no claims about tariff incidence or comparative advantage.
- The 2019 List 4A window runs into the 2020 COVID shock.
- Section 232 duties on Canada and Mexico were lifted in May 2019, inside the after window of the June 2018 extension.
