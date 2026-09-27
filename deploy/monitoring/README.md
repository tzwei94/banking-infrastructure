# Task telemetry contract

Build from the deployment repository root with `docker build -t banking-alloy:local deploy/monitoring`. Each application Fargate task has exactly one sidecar; migration and bootstrap tasks contain only Java. Its loopback receiver accepts OTLP/HTTP on 4318; it scrapes the loopback Actuator listener on 9000 every 60 seconds. Neither listener is in an ECS ingress rule or ALB target. `constants.hostname` supplies a distinct metric instance per task.

`TELEMETRY_USERNAME` and `TELEMETRY_PASSWORD` come from Secrets Manager. This implementation uses HTTP Basic authentication over verified public HTTPS. The telemetry ingestion gateway must implement that contract; browser login and Cloudflare Access redirects are incompatible. `TRACES_BASE_URL` excludes `/v1/traces`; the OTLP HTTP exporter appends it. Loki and metrics variables contain their complete API paths. Verify ingestion, authentication and query isolation in the target environment; configuration and local fixture success do not establish public endpoint readiness.

Logback writes JSON with OTel `trace_id`/`span_id` fields to shared files; these identifiers never become Loki stream labels. Files rotate at 10 MiB with a 30 MiB archived-file cap (plus the active file). Alloy has read-only log access and a separate writable state volume. The application’s console WARN/ERROR output is a bounded CloudWatch fallback, retained seven days; administrative task output and Alloy warnings also use the task log group. ECS uses non-blocking logging with a 1 MiB buffer per container. Loki retries five times, with at most ten seconds between retries; this pipeline can drop logs during an extended outage. Metrics WAL age is capped at fifteen minutes; queue capacity is 2,500 samples per shard, two shards maximum. Trace memory limiting, 128 queued batches and a sixty-second retry horizon bound the trace path. Task termination loses ephemeral files/WAL; none of these settings promises durable buffering.

The initial task limit is 512 CPU units / 1,024 MiB: Java 704 MiB and Alloy 320 MiB. The local smoke test exercises these memory limits; production load, two-task cardinality, shutdown delivery and long outages still require measurement on AWS. OTel samples 10% of new traces, follows parent sampling, and disables the OpenTelemetry starter's log and metric exporters to avoid duplicate delivery. Local smoke uses 100% sampling.

Useful acceptance queries after deployment:

- Prometheus: `up{job="banking-api"}` must contain two distinct healthy `instance` labels; inspect `http_server_requests_seconds_count` and `banking_operations_total`.
- Loki: `{service_name="banking-api"} | json` should show bounded operation messages and trace IDs, without account IDs, balances, JWTs or request bodies.
- Tempo: retrieve a sampled request's `trace_id` from Loki using the private query UI/API. Verify HTTP and JDBC spans.
- Reject anonymous writes to all three public ingestion routes and reject public query/admin routes.
- Stop the test gateway briefly and then replace a task; measure recovery and document lost data. Do not infer delivery from Alloy health alone.

The monitoring operator manages Grafana data sources, dashboards and storage. AWS Terraform creates ALB/ECS/RDS/runner alarms and budget notifications; confirm the SNS email subscription. The budget alert is account-wide and monthly: it is a warning, not a US$100 spending cap or an automatic shutdown.

The pinned Alloy 1.20.0 image passed a prior point-in-time [recorded vulnerability scan](security-review.md). The publication script repeats the scan before pushing.

## Reuse this image

The custom image contains official Alloy and a generic default pipeline. It runs
as UID/GID 10001, with no database certificates, Java runtime or initialization
script. Build from the repository root with:

```sh
docker build -t reusable-alloy:local deploy/monitoring
```

The default pipeline reads log files, scrapes Prometheus metrics and receives
OTLP/HTTP traces. Applications must emit those protocols. Use a replacement
configuration for different receivers, signal combinations or authentication.

| Variable | Default | Banking deployment value |
| --- | --- | --- |
| `SERVICE_NAME` | `app` | `banking-api` |
| `LOG_GLOB` | `/var/log/app/*.log` | `/var/log/app/application*.log` |
| `METRICS_TARGET` | `127.0.0.1:9090` | `127.0.0.1:9000` |
| `METRICS_PATH` | `/metrics` | `/actuator/prometheus` |
| `METRICS_SCRAPE_INTERVAL` | `60s` | `60s` |
| `METRICS_SCRAPE_TIMEOUT` | `10s` | `10s` |
| `OTLP_HTTP_ADDRESS` | `127.0.0.1:4318` | same |

Set `ENVIRONMENT`, `LOKI_URL`, `METRICS_URL`, `TRACES_BASE_URL`,
`TELEMETRY_USERNAME` and `TELEMETRY_PASSWORD` for the bundled pipeline. Set the
scrape timeout no higher than the scrape interval. Loopback addresses assume a
shared network namespace (as in the ECS task and local Compose); for separate
containers, configure the scrape target and OTLP listener for that network.
Destinations and credentials are supplied at runtime, never baked into the image.

A custom config replaces the entire default pipeline without rebuilding:

```sh
# Run with a config whose required environment variables are provided separately.
docker run --rm --read-only \
  --mount type=bind,src="$PWD/my-config.alloy",dst=/etc/alloy/config.alloy,readonly \
  --mount type=volume,src=my-alloy-state,dst=/var/lib/alloy/data \
  reusable-alloy:local
```

Add a read-only log mount if that config reads files. The config must be readable
by UID 10001; add environment variables and network settings for its components.
For Kubernetes, the equivalent Deployment pod-spec fragment is:

```yaml
containers:
  - name: alloy
    image: YOUR_REGISTRY/reusable-alloy@sha256:YOUR_VERIFIED_DIGEST
    securityContext:
      runAsUser: 10001
      runAsGroup: 10001
      readOnlyRootFilesystem: true
    volumeMounts:
      - name: alloy-config
        mountPath: /etc/alloy/config.alloy
        subPath: config.alloy
        readOnly: true
      - name: alloy-state
        mountPath: /var/lib/alloy/data
securityContext:
  fsGroup: 10001
volumes:
  - name: alloy-config
    configMap:
      name: alloy-config
      defaultMode: 0444
  - name: alloy-state
    emptyDir: {}
```

Create the ConfigMap with `kubectl create configmap alloy-config
--from-file=config.alloy=./my-config.alloy` (one command). Supply the environment
and any log volumes required by your config. Restart the pod to apply changes to
this `subPath` mount. This is an integration example, not an additional deployment
in this repository; ECS uses the bundled config and environment overrides.

## Direct startup and volume ownership

The Java and Alloy Dockerfiles prepare `/var/log/app` with UID/GID 10001 and mode
0700. Both declare that volume path so fresh Docker/ECS volumes have compatible
ownership whichever image populates the volume first. Java mounts logs writable;
Alloy mounts them read-only. Alloy owns `/var/lib/alloy/data`; Java declares `/tmp`
with standard mode 1777. Containers run directly as non-root users.

Existing volumes and host bind mounts retain their existing permissions. For an
existing local volume, stop its users, back it up, then explicitly repair only
that log volume's ownership to 10001:10001 and directory mode to 0700, or choose a
new volume name after deciding whether the old logs are needed. Do not delete all
Compose volumes to fix permissions: that may remove database data. Host-mounted
log files must also be readable by UID 10001.

Java images package the checksum-verified database CA at
`/opt/app/certs/rds-ca.pem`; app, migration and bootstrap use it with
`sslmode=verify-full`. Alloy has no database responsibilities. Certificate rotation
requires a Java-image rebuild, not an Alloy rebuild. When upgrading from older volume/certificate conventions, rebuild and publish both
images before deploying the matching task definitions; retain previous image digests
and task definitions for rollback. Local tests do not establish live Fargate
volume initialization or RDS connectivity.

## Local verification

After building both images, run from the deployment repository root:

```sh
bash deploy/scripts/validate.sh
ALLOY_IMAGE=banking-alloy:local uv run deploy/tests/check_alloy_runtime.py
API_IMAGE=banking-api:local ALLOY_IMAGE=banking-alloy:local \
  bash deploy/tests/test-container-volumes.sh
```

The telemetry fixture decodes received log/metric payloads to check a second application's
service labels and checks readiness with a mounted config replacement. It does not
send traces or verify public HTTPS authentication; the application smoke fixture
checks the three-signal local banking path. The volume check covers
both initialization orders, non-root writes, read-only logs, certificate access
and preservation of existing root-owned volumes. Run `scripts/local-smoke.sh` in
the application repository for the full banking telemetry path.

## Runner host metrics

`runner.alloy` is a separate host-metrics pipeline; it is not used by the ECS
sidecar. On the EC2 runner, provision `/etc/alloy/runner.env` as a root-owned
mode-0600 file containing `METRICS_URL`, `TELEMETRY_USERNAME` and
`TELEMETRY_PASSWORD`. Run `deploy/provisioning/install-runner-alloy.sh VERSION SHA256` as root through SSM, using a reviewed Linux amd64 release archive checksum.
The installer starts `banking-alloy.service` as the `alloy` user with a 256 MiB
memory cap and persistent state at `/var/lib/alloy`. Confirm service status and
remote `job="banking-runner"` samples separately. Terraform’s runner status alarm
does not monitor disk usage; configure a host disk alert in the external monitoring
service.
