# Alloy image validation — 27 September 2026

The deployment image now pins `grafana/alloy:v1.20.0` at OCI index digest `sha256:f111cce835516c5f99166342be7038496b52ced16667be5a11e19258a3e4cd30`. The linux/amd64 child digest is `sha256:f269084e6fea16d640d2693d2516b759cf3ec8be4bb7cdd7c2eb11ea522b77ff`.

The built linux/amd64 image passed Alloy configuration validation. Trivy 0.74.0, using its refreshed vulnerability database, reported zero fixable HIGH/CRITICAL findings in the OS packages and Alloy Go binary (`--scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`). This clears the previously recorded publication blocker for this candidate; it is not a claim of zero vulnerabilities at other severities or without fixes. The publication script repeats validation and scanning before pushing.

The local application smoke test also passed with the new linux/amd64 Alloy image: authenticated API operations, persistence across API restart, collector outage/recovery, delivery of logs/metrics/traces, and JSON log trace/span correlation and account redaction.

No AWS image publication or deployment was performed during these local checks. Release details: https://github.com/grafana/alloy/releases/tag/v1.20.0.

## Historical scan — 25 September 2026


Pinned `grafana/alloy:v1.19.2` digest `sha256:b8ec653c44235fbe910879145dac3597d66b0aaecf60bcbbe82580767771a839` contains `google.golang.org/grpc v1.83.0`. Trivy 0.74.0 reports two fixable HIGH dependency findings:

- [CVE-2026-84304 / gRPC-Go frame fragmentation DoS](https://github.com/grpc/grpc-go/security/advisories/GHSA-vp52-pcj8-j9qc), patched in gRPC-Go 1.83.1.
- [CVE-2026-84445 / gRPC-Go xDS server crash](https://github.com/grpc/grpc-go/security/advisories/GHSA-2v4p-qf9q-27wj), patched in gRPC-Go 1.83.2.

The configured sidecar enables OTLP HTTP on loopback, with no gRPC receiver or xDS server. This limits the exposed paths but is not represented as an image-level fix. This was the blocker for v1.19.2; the v1.20.0 validation above supersedes it. Keep the publication scan gate enabled.

The Java 25 / Spring Boot 4.1.1 migration uses Tomcat 11.0.26 to address findings in the managed 11.0.24 version. The rebuilt Java image has zero fixable HIGH/CRITICAL findings in Trivy 0.74.0. Other previous Java dependency overrides were removed in favor of the newer Spring Boot BOM. Scan results are point-in-time dependency evidence, not a complete security assessment.
