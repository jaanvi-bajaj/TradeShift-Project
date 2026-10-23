# Cost estimate (Week 2: cloud economics)

The stack uses the smallest sizes the Sandbox allows and no NAT Gateway. The figures are
**approximate us-east-1 on-demand list prices**. Before the presentation, check them in the
[AWS Pricing Calculator](https://calculator.aws/) with the same quantities and put the
calculator's share link here.

## What runs

| Resource | Count | Size | Approx. price |
|---|---|---|---|
| Web servers (EC2) | 2 (up to 3 when scaled out) | t3.micro | ~US$0.0104 per hour each |
| Batch server (EC2) | 1 | t3.small | ~US$0.0208 per hour |
| RDS PostgreSQL | 1, single-AZ | db.t3.micro, 20 GB gp2 | ~US$0.018 per hour + ~US$0.115 per GB-month |
| Application Load Balancer | 1 | – | ~US$0.0225 per hour + capacity units (tiny at our traffic) |
| EBS volumes | 16 GB + 20 GB (batch), 8 GB per web server | gp2 | ~US$0.10 per GB-month |
| Public IPv4 addresses | ~5 (3 instances, 2 for the ALB) | – | ~US$0.005 per hour each |
| S3 | a few GB | Standard, raw/ moves to Standard-IA after 30 days | ~US$0.023 per GB-month |
| CloudWatch | logs (7-day retention), 5 alarms, 1 dashboard | – | mostly within free-tier amounts |

## Per Sandbox session (3 hours)

| Item | Approx. cost |
|---|---|
| 2 web servers × 3 h | US$0.06 |
| Batch server × 3 h | US$0.06 |
| RDS × 3 h (+ storage) | US$0.06 |
| ALB × 3 h | US$0.07 |
| Public IPv4 × 5 × 3 h | US$0.08 |
| EBS, S3, CloudWatch | US$0.03 |
| **Total** | **about US$0.35 per session** |

So the US$10 budget alert covers roughly 25–30 full sessions. A scale-out test adds one
t3.micro for a few minutes, a fraction of a cent.

## On-demand vs Spot (the Week 2 discussion)

- **Spot** instances cost up to ~70–90% less, but AWS can take them back with two minutes' notice.
- **The web tier** could use Spot behind the ALB with a mix of instance types, because the servers are stateless and the Auto Scaling Group replaces lost ones. The Sandbox allows **on-demand only**, so we use on-demand.
- **The batch job** is long-running but restartable (step markers, downloads skip finished files), so it would also suit Spot outside the Sandbox.
- **Reserved Instances / Savings Plans** only pay off for steady 24/7 use over one to three years, which a course project is not.

## What we did to keep costs down

- No NAT Gateway (about US$0.045 per hour plus data, more than all the servers together).
- Smallest instance classes; gp2 volumes sized to need.
- Lifecycle rule moves raw API files to Standard-IA after 30 days.
- Log retention set to 7 days.
- The whole stack is deleted after each session (and the Sandbox removes anything left).
- An optional AWS Budgets alert at US$10 (`EnableBudget=true`) where Budgets is available.
