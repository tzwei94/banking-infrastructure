# Memory capacity and scaling proposal

The live `banking-dev` service in account `662371887521`, Singapore
`ap-southeast-1`, currently uses 0.5 vCPU / 1 GiB service tasks, CPU target 60%,
and 2–4 tasks. This change is opt-in and needs approval before live application.
Both new variables default to false, preserving existing profiles.

## Proposed settings

| Setting | Existing | Proposed |
| --- | --- | --- |
| Service task CPU / memory | 512 units / 1024 MiB | 512 units / 2048 MiB |
| Java hard limit / reservation | 704 / 512 MiB | 1536 / 1024 MiB |
| Alloy hard limit / reservation | 320 / 128 MiB | 512 / 256 MiB |
| Alloy trace heap limiter hard / spike / soft | 64 / 16 / 48 MiB | 256 / 64 / 192 MiB |
| CPU scaling target | 60% | 60% |
| Memory scaling target | Absent | 70% |
| Task capacity | 2–4 | 2–4 |
| Scale-out / scale-in cooldown | 30 / 60 seconds | 30 / 60 seconds |

Enable `memory_headroom_enabled` for the larger service task and limiter settings;
enable `memory_autoscaling_enabled` to add memory target tracking when both
`autoscaling_enabled` and `service_enabled` are already true. Migration and
bootstrap task sizes remain 1 GiB. No IAM permissions, networking, database pool,
trace sampling, or queue sizes change.

The JVM keeps `MaxRAMPercentage=55`: the proposed Java limit allows approximately
845 MiB maximum heap and 691 MiB for native memory, metaspace and other overhead.
Alloy keeps approximately 256 MiB beyond its hard heap limiter for other memory.
Heap limits are not RSS guarantees; monitor actual container memory after rollout.

The preceding 24-hour CloudWatch service-memory readings on 2026-10-05 were
67.2% average and 72.7% peak. A 70% target leaves 30% headroom in the reported
ECS metric; it is not a guarantee of 30% free physical task memory.
The new capacity should reduce utilization initially, but JVM heap growth and
per-task overhead mean this is not a guaranteed halving. Service-average memory
can also hide an overloaded container. Monitor Java and Alloy individually.
[AWS documents service memory utilization](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/available-metrics.html)
as memory used divided by memory reserved, with MemoryReservation used instead
of total memory when specified. These containers reserve 640 MiB before and
1280 MiB after the change. Therefore the 70% policy target must not be described
as 70% of the physical 2 GiB task limit. The agent's host-resource accounting
method is not proof of the Fargate CloudWatch metric denominator.

Both task hard capacity and summed reservations double, so unchanged byte usage
should initially halve utilization; this does not ensure utilization stays low
as the JVM grows its heap. Container Insights is disabled, so independent
MemoryUtilized/MemoryReserved corroboration is unavailable. Grafana displays
the actual AWS percentage and configured capacity separately, without converting
utilization to bytes. JVM heap retention can delay scale-in because both policies
must agree before removal. The 70% target is an initial conservative choice,
not a measured workload optimum.

[AWS permits 2 GiB with 0.5 vCPU](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-cpu-memory-error.html).
With both policies, [AWS scales out when either policy requires it, and scales in
only when both scale-in-enabled policies agree](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-autoscaling-targettracking.html).
Scale-in is suspended during ECS deployments. Additional tasks help only when
memory pressure responds to distributing traffic; they do not repair a leak or
a shared downstream bottleneck. Existing 100%/200% rolling-deployment bounds can
temporarily run twice the desired task count.

## Cost

Singapore Linux/x86 Fargate on-demand rates, verified 2026-10-05 through the
[AWS ECS regional price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECS/current/ap-southeast-1/index.json):
$0.05056/vCPU-hour and $0.00553/GiB-hour. Assuming 730 hours:

| Continuous task count | Existing compute/month | Proposed compute/month | Extra memory cost/month |
| --- | --- | --- | --- |
| 2 | $44.98 | $53.06 | $8.07 |
| 4 | $89.97 | $106.11 | $16.15 |

These are task-compute estimates, excluding ALB, RDS, storage, data transfer,
taxes and deployment overlap. Extra tasks triggered by either policy incur
their full CPU and memory price while running.

## Trace warning evidence and limitation

CloudWatch `/ecs/banking-dev`, 2026-10-04 15:40 UTC, showed Alloy refusing spans
above its 48 MiB soft threshold, the Java exporter receiving loopback HTTP 503,
and Java's 2048-span queue dropping spans. The remote trace exporter also received
HTTP 429 reporting a 262144-byte/second ingestion limit and 524288-byte burst;
retry exhaustion dropped 512-span batches. These establish trace loss, not
banking API HTTP 503 or an OOM. Remote throttling contributing to backlog and
heap pressure is an inference.

The larger limiter absorbs more bursts but does not remove the downstream
256 KiB/second ceiling. More tasks may increase aggregate trace output. A sampling
or remote ingestion/capacity change requires separate investigation and approval;
the receiver's physical placement on PVE02 has not been verified.

## Application sequence after approval

1. Pass Deployment CI, including real Alloy validation with both default and
   expanded heap settings. Publish the modified Alloy image through its existing
   build, validation and vulnerability-scan workflow; retain the immutable digest.
2. Refresh the private dev profile from the successful release manifest. Set the
   two opt-ins true and select the new Alloy digest. Generate and inspect an
   operator Terraform plan. Expect the added memory policy and service candidate
   definition; preserve the active service revision until release promotion.
   Do not broaden the release role or bypass the release infrastructure guard.
3. Apply only the approved operator plan, then use the normal release workflow
   with the current application digest, new Alloy digest and `read_only_smoke=true`.
   This avoids account transactions in the default smoke verification.
4. Verify 2–4 healthy tasks, matching digest and memory limits, both live targets,
   generated alarms and scale-in settings. Observe memory and trace exporter
   errors without starting sustained load. Any live load needs separate approval.

Rollback application health using the successful manifest's retained prior task
definition. Reverting the opt-ins/policy requires a separately inspected operator
plan; do not delete AWS-managed target-tracking alarms directly.
