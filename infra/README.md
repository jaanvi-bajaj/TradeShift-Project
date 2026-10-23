# infra/

| Path | What it does |
|---|---|
| `cloudformation/tradeshift.yaml` | The whole environment in one stack (network, security, storage, database, compute, scaling, monitoring). See RUNBOOK.md for what each section does. |
| `cloudformation/parameters.example.json` | Parameter names for a CLI deploy. Values for secrets are placeholders; never commit real ones. |
| `scripts/install_app.sh` | Run by user data: downloads and checks the wheel bundle, creates the virtualenv, starts the CloudWatch agent |
| `scripts/web_start.sh` | Run by user data on web servers: systemd unit for gunicorn, waits for `/health` |
| `scripts/batch_run.sh` | Run by user data on the batch server: mounts the EBS data volume at `/data`, runs the pipeline |
| `scripts/cloudwatch-agent.json` | Which log files go to CloudWatch Logs |

Lint the template with `cfn-lint infra/cloudformation/tradeshift.yaml`.
