# Local IT and Incident Monitoring

Fictional Meeple & Mug services need checks that distinguish one failed response from an
incident. This demo probes ONLY loopback addresses or runs fully offline simulation.

## Run

```
PYTHONPATH=projects/monitoring/src python -m meeple_monitor.monitor \
  --database /tmp/meeple-monitor.sqlite --simulate down
```

Repeat twice to open an incident, then run with `--simulate healthy` to resolve it.
Omit `--simulate` only for an authorized local HTTP service (the default target is
127.0.0.1:8000/health). No remote IP, DNS name, HTTPS endpoint, automatic redirect,
or external infrastructure is accepted.

## Algorithm

Inputs: a local service URL, status, measured milliseconds, threshold and consecutive
failure count. Output: stored measurement and incident state. Sequence: persist, query
recent readings, iterate through them, then decide whether to open, keep, or close an
incident. The loop costs O(k) time for k recent readings and O(k) query space. If there
are fewer than k samples, no incident starts; a healthy response clears a live incident.

Why: two failures avoid noisy first-error alarms. Alternatives include rolling percentiles
and multiple-region probes, which are inappropriate for this isolated learning example.
A status 200 response slower than the threshold is considered unhealthy.

`PYTHONPATH=projects/monitoring/src pytest -q projects/monitoring/tests`

ADR: standard-library HTTP reduces dependencies. Restricting the URL and connecting only
to 127.0.0.1 reduces server-side request forgery risk in a local-only demo. This is not a
full observability stack or public monitoring product.
