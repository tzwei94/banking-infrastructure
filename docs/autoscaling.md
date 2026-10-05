# ECS service autoscaling

The dev ECS service can opt into native Application Auto Scaling. Enable it only through an operator-reviewed infrastructure plan after approving its task and cost ceiling. App release workflows cannot change scaling policies.

## Proposed settings

| Setting | Value |
| --- | --- |
| Opt-in flag | `autoscaling_enabled = true` (default `false`) |
| Desired capacity range | 2–4 tasks |
| Metric | `ECSServiceAverageCPUUtilization` |
| Target | 60% |
| Scale-out cooldown | 30 seconds (demo) |
| Scale-in cooldown | 60 seconds (demo) |
| Scale-in | Enabled; ECS suppresses it during deployments |
| Task size | Existing 0.5 vCPU / 1 GiB Linux x86 task, including Alloy |

CPU target tracking adds/removes tasks to approach the target; it is not an instruction to add exactly one task whenever one sample exceeds 60%. CloudWatch evaluation and task startup add delay. Insufficient metric data does not cause scale-in. AWS owns the policy's generated alarms. Existing CPU/memory >80% SNS notification alarms remain unchanged.

The two-task minimum preserves baseline capacity. Four tasks allow a bounded initial increase for the existing `db.t4g.micro`; they can open up to 32 application Hikari connections (8 per instance), excluding migration and administrative connections. This is not a verified database capacity limit. Database waits and row-lock contention can increase latency without high CPU; this policy does not scale on latency or request count. Watch pool waits, RDS CPU/connections and latency before increasing the ceiling. Optional [memory scaling and task headroom](memory-scaling.md) adds a second 70% target through a separately reviewed operator plan. Retained JVM heap can keep memory elevated and delay scale-in even after CPU load falls.

The four-task limit applies to desired capacity. Existing 100% minimum healthy / 200% maximum deployment settings permit temporarily up to eight running/pending tasks when desired capacity is four. Health grace remains 120 seconds; ALB readiness remains `/readyz` with a 30-second interval, 5-second timeout and thresholds 2 healthy / 3 unhealthy.

## Demo timing

The 30-second scale-out / 60-second scale-in cooldowns are a reasonable demonstration starting point, not a universal optimum. They reduce waiting between successive scaling actions compared with the earlier 60/300 proposal, at the cost of more task churn or oscillation under fluctuating load. The 2–4 task bounds and 60% CPU target remain unchanged.

Cooldown is the wait after a scaling activity for its effects to settle. It does not control the time from starting/stopping load to the first scaling action. Scale-out may also bypass its cooldown for a larger adjustment; scale-out can interrupt an active scale-in cooldown. See [AWS cooldown semantics](https://docs.aws.amazon.com/autoscaling/application/userguide/target-tracking-scaling-policy-overview.html).

This policy uses standard-resolution CPU metrics. Target tracking evaluates these at one-minute granularity, and AWS generates the alarm evaluation windows. Live readback on 2026-10-04 verified a high alarm with CPU >60%, period 60 seconds and three evaluation periods, and a low alarm with CPU <54%, period 60 seconds and fifteen evaluation periods. Both have actions enabled. These evaluation windows are separate from the 30/60-second cooldowns. Read the policy’s `Alarms` list and describe those CloudWatch alarms to inspect `Period`, `EvaluationPeriods`, `DatapointsToAlarm` and `Threshold` when checking future behavior. Do not edit the AWS-managed alarms to accelerate the demo.

Allow several minutes for automatic scale-out after sustained CPU pressure, plus image download, Fargate provisioning, Java startup and readiness checks. The existing ALB interval is 30 seconds. Newly registered targets need only one successful health check; the threshold of two applies to recovery from unhealthy state. The 120-second service grace period lets startup proceed before ECS reacts to failed health checks; it is not a mandatory two-minute sleep before a ready target can receive traffic. See [AWS health-check behavior](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/load-balancer-healthcheck.html).

For a complete automatic demonstration, reserve roughly 20–30 minutes as a planning allowance, rather than expecting both directions in 60 seconds. CPU must actually exceed the target for the high alarm to breach; the previously proposed 10-request/second balance workload may be too light. Load ceilings and duration still need separate approval. Do not deploy during the demonstration: ECS suppresses automatic scale-in while deployments are in progress. After stopping approved load, keep observing the low alarm and scaling activity history; low utilization, alarm evaluation, cooldown, deregistration and graceful shutdown all affect the return to two tasks. A longer evaluation window or insufficient data can take longer than this allowance.

For a short presentation, show automatic scale-out, then discuss the slower automatic scale-in or show a previously recorded complete cycle. Another separately approved option is an operator manually returning desired capacity to two after load has stopped and utilization is low. Label that as a manual reset, not evidence of automatic scale-in; an active policy may scale out again if load remains high. No manual reset command is executed or included in the patch's automation.

AWS introduced [20-second high-resolution ECS autoscaling metrics](https://aws.amazon.com/blogs/aws/amazon-ecs-introduces-new-high-resolution-metrics-for-faster-service-auto-scaling/) in June 2026. They require enabling service metrics and selecting the high-resolution policy metric, with additional CloudWatch charges. This patch keeps the existing standard-resolution metric; a faster-metric option would need a separate cost/configuration proposal and approval. AWS benchmark timings are not guarantees for this app.

## Terraform and releases

`aws_ecs_service.app` starts at two tasks and ignores later `desired_count` drift so a release will not reset capacity selected by Application Auto Scaling. This ignore also applies while autoscaling is disabled: an operator must manage any manual count change explicitly. Disabling autoscaling removes its policy/target but does not reset the live task count to two.

Release verification still requires the promoted task definition, zero pending tasks, running count equal to desired count, and a healthy ALB target for every desired task. It allows up to two minutes of bounded retries after the ECS stable waiter for in-range scaling and ALB convergence, and rechecks desired capacity after target-health reads. Wrong revisions and out-of-range counts fail immediately. It accepts desired counts 2–4 when the release's persisted dev configuration has `autoscaling_enabled = true`; otherwise it requires two. After the approved operator apply, synchronize this flag into the GitHub dev environment’s `DEV_TFVARS_JSON` variable used by release jobs. Keep both copies aligned. It is an infrastructure setting, not a release workflow input.

The deploy IAM role receives only the Application Auto Scaling describe/tag-list reads required for Terraform refresh, limited by `aws:RequestedRegion` to the configured region. The release plan guard continues rejecting scaling target/policy mutations. Enabling, disabling or changing scaling limits requires an operator plan and identity with the corresponding Application Auto Scaling permissions. Do not grant broad scaling writes to the release role to bypass this guard.

For a fresh installation, complete the first release with autoscaling disabled, then enable it through an operator plan. Preparation with no service never registers a scaling target.

## Review and activation prerequisites

Activated with explicit task/cost and IAM approval on 2026-10-04 in account `662371887521`, region `ap-southeast-1`. Terraform applied two resource creates and one deploy-role policy update, with no destruction. Live readback confirmed the approved target/policy, unsuspended scaling, the AWS-managed service-linked role, and the three Singapore-scoped read permissions. The app stayed on task revision 5 with two desired/running tasks, zero pending and two healthy ALB targets. The low alarm was in `ALARM` because utilization was low; the minimum of two prevents further scale-in. No load test or banking transaction was run. Repository defaults remain opt-in; the active operator and GitHub dev release configurations enable it.

For a new installation or later changes, use these prerequisites:

1. Renew that existing profile locally with `aws login --profile nextgen.athena --region ap-southeast-1` and verify `sts get-caller-identity` matches expected account `662371887521`. Ignore configured emulator endpoint overrides for these checks.
2. Describe ECS service `banking-dev` in cluster `banking-dev`, region `ap-southeast-1`. Check its desired/running/pending counts, active task definition and deployment state before planning.
3. Inspect Application Auto Scaling targets, policies, scheduled actions and suspension state for `service/banking-dev/banking-dev`. If resources already exist outside Terraform, reconcile/import the existing target and selected policy rather than creating a competing policy. Review all remaining policies; another policy or schedule can affect task counts.
4. Verify the ECS Application Auto Scaling service-linked role exists, or that the operator has permission for AWS to create `AWSServiceRoleForApplicationAutoScaling_ECSService` through `ecs.application-autoscaling.amazonaws.com`. Check Fargate quotas, private-subnet IP capacity and database headroom. These are prerequisites, not changes made by this patch.
5. Approve the proposed settings and cost assumptions below. Add `"autoscaling_enabled": true` to the existing private dev variables, preserving the active task ARN, immutable image digests and all other values. Use the existing backend configuration and operator plan workflow (`DEV_VARS` / `DEV_BACKEND` with `make plan`). Review a fresh saved plan; do not reuse a prior plan.
6. Expected changes are one scaling target, one CPU target-tracking policy and additional read-only deploy-role permissions. AWS creates the policy's managed CloudWatch alarms. Investigate unrelated infrastructure, task-definition or desired-count changes before applying. Application code, task sizing, database, telemetry and existing alarms are unchanged.
7. Apply only after specific approval of the live plan/settings. Verify live target bounds, policy configuration, scale-in suspension and healthy service capacity afterward. A load test is a separate approved action.

## Cost estimate

AWS's public Singapore price list, published 2026-09-11 and checked 2026-10-04, lists Linux x86 Fargate on-demand rates of US$0.05056/vCPU-hour and US$0.00553/GB-hour. At the existing task size:

- One task: `0.5 × 0.05056 + 1 × 0.00553 = US$0.03081/hour`.
- Both extra tasks above baseline: US$0.06162/hour; approximately US$44.98 extra for 730 hours continuously at four tasks.
- Two-task baseline: approximately US$44.98/month in task compute; four-task compute: approximately US$89.97/month using the same 730-hour assumption.

These are gross on-demand compute estimates, excluding credits, discounts, taxes, ALB, RDS, networking, telemetry/log ingestion and managed CloudWatch alarms. They are not a total spending cap. Rollout overlap can briefly add more compute; at desired four, up to four additional rollout tasks cost another US$0.12324/hour while all run. The default 20-GiB ephemeral storage allowance is included; no extra storage is configured here.

Sources: [AWS public regional price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECS/current/ap-southeast-1/index.json), [Fargate pricing](https://aws.amazon.com/fargate/pricing/), [ECS target tracking behavior](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-autoscaling-targettracking.html), [ECS scaling service-linked role](https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-service-linked-roles.html).

## Verification

Use `make verify` for the normal repository checks. The added Terraform mock cases cover opt-in behavior, absent-service preparation, target bounds/CPU/cooldowns and read-only release permissions. Release unit tests cover healthy capacity at 2/3/4, out-of-range counts, unhealthy or pending capacity, wrong revisions and rejection of policy changes. Mocked tests do not verify live AWS permissions or performance.
