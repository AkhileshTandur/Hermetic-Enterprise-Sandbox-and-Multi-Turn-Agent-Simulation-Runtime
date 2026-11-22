# Five-minute demo

1. Start Compose and open localhost:8000. Launch the default create/read scenario.
2. Refresh and inspect the completed report. Show that the second call sees the first call's ticket.
3. Run the same scenario twice. Ticket IDs and final state repeat, while run IDs and schemas differ.
4. Add `"inject_transient_after_create": true`. The first tool records two attempts but final state has one ticket.
5. Set `"expected_tickets": 2`. Show agent validation failure with a completed harness.
6. Run tests to demonstrate cancellation and timeout cleanup.
7. Optionally start the tracer separately, set the OTLP endpoint, and inspect the same trace ID there.

Use the benchmark output and documented environment when reporting performance.
