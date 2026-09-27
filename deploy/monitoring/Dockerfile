# Reusable telemetry runtime; mount a different config for other pipelines.
FROM grafana/alloy:v1.20.0@sha256:f111cce835516c5f99166342be7038496b52ced16667be5a11e19258a3e4cd30
USER root
RUN mkdir -p /var/lib/alloy/data /var/log/app \
    && chown -R 10001:10001 /var/lib/alloy /var/log/app \
    && chmod 700 /var/lib/alloy/data /var/log/app
COPY config.alloy /etc/alloy/config.alloy
VOLUME ["/var/lib/alloy/data", "/var/log/app"]
USER 10001:10001
CMD ["run", "--server.http.listen-addr=127.0.0.1:12345", "--storage.path=/var/lib/alloy/data", "/etc/alloy/config.alloy"]
