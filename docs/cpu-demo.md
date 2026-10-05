# Bounded CPU demo deployment

The dev Terraform root enables `cpu_demo_enabled=true` by default and forwards
it as `CPU_DEMO_ENABLED=true` to the app container. The reusable ecs-service module
and base Java app default false. Alloy and migration containers receive no flag.
No IAM, JWT, security group, WAF, network or autoscaling-policy changes are needed.

The endpoint is `POST /demo/cpu`, authenticated by the existing normal JWT policy.
It accepts 50–500 ms of fixed-size hashing, one job per task, no queue and a
100 ms recovery gap. Excess traffic gets 429. It touches no banking data.

Release through the established app CI → scanned immutable ECR digest → deployment
workflow with `read_only_smoke=true` for this endpoint release. This checks token
issuance, readiness, liveness and version without account requests or CPU work.
Keep the current Alloy digest and autoscaling settings (2–4 tasks, 60%
average service CPU). The existing deployment workflow applies migrations and
runs its existing synthetic net-zero banking smoke by default (a 0.01 deposit, idempotent
retry and matching withdrawal). That smoke adds synthetic ledger records even
though it restores the balance. The separate CPU verification requires only one
small authenticated CPU request, plus anonymous denial and health checks.

To disable work, set `cpu_demo_enabled=false` in the dev profile and deploy a new
task revision. To roll back the application, use B. Deploy or Roll Back with
action=rollback and `read_only_smoke=true`; it promotes the prior successful task definition without
reversing database migrations. A prior task definition without this endpoint also
removes its availability. Do not change the task ARN or perform update-service
outside the Terraform-owned release workflow.

The optional separate k6 load script is capped at 4 CPU requests/sec, 8 total VUs
and 300 seconds plus in-flight cleanup. No load is executed by deploying or
verifying this endpoint. Obtain separate live target/load-ceiling approval first.
