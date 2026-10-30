#!/usr/bin/env python3
"""Check the completed wall-clock soak against an explicit resource budget."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.report.read_text())
    policy = json.loads(args.policy.read_text())
    checks = {}
    baseline = data["baseline"] or data["initial"]
    cpu_total = data["cpu_average_percent"] + (
        data["metrics"]["children_cpu_s"] - data["initial"]["children_cpu_s"]) / data["elapsed_s"] * 100
    count = sum(data["heartbeat_histogram_ms"].values())
    accumulated = 0
    p99 = None
    for limit in (1, 5, 10, 50, 100, 250, 500, 1000):
        accumulated += data["heartbeat_histogram_ms"].get(str(limit), 0)
        if count and accumulated >= count * .99:
            p99 = limit
            break
    values = {"elapsed_s": data["elapsed_s"], "cpu_ui_and_reaped_children_percent": cpu_total,
        "rss_peak_growth_mib": (data["peak"]["rss_kb"] - baseline["VmRSS"]) / 1024,
        "rss_trend_mib_per_hour": data["rss_trend_kb_per_hour"] / 1024 if data["rss_trend_kb_per_hour"] is not None else None,
        "fd_peak_growth": data["peak"]["fds"] - baseline["fds"],
        "widget_peak_growth": data["peak"]["widgets"] - baseline["widgets"],
        "heartbeat_p99_upper_ms": p99, "heartbeat_max_delay_ms": data["heartbeat_max_delay_ms"],
        "read_mib_per_hour": (data["metrics"]["io"]["read_bytes"] - data["initial"]["io"]["read_bytes"]) / 1024**2 / (data["elapsed_s"] / 3600),
        "write_mib_per_hour": (data["metrics"]["io"]["write_bytes"] - data["initial"]["io"]["write_bytes"]) / 1024**2 / (data["elapsed_s"] / 3600)}
    checks["completed_for_requested_duration"] = data["status"] == "complete" and values["elapsed_s"] >= policy["minimum_duration_s"]
    checks["warmup_observed"] = (data["baseline"] is not None and
                                 data["baseline"]["elapsed_s"] >= policy["warmup_s"])
    checks["harness_no_failures"] = not data["failures"]
    if "source_unchanged" in data:
        checks["runtime_source_unchanged"] = data["source_unchanged"] is True
    for name, maximum in policy["maximums"].items():
        checks[name] = values[name] is not None and values[name] <= maximum
    checks["no_owned_child_after_shutdown"] = (data["status"] == "complete" and
        data["active_qprocesses"] == 0 and not data["metrics"]["children"])
    counters = data["job_counters"]
    checks["all_worker_results_delivered"] = counters["worker_started"] == counters["worker_completed"]
    if "planned_workers" in data:
        checks["all_planned_workers_ran"] = counters["worker_started"] == data["planned_workers"]
    checks["all_cancellations_delivered"] = counters.get("cancel_started", 0) == counters.get("cancel_completed", 0)
    checks["sample_buffer_bounded"] = data["samples"] <= data["samples_cap"]
    checks["queues_bounded"] = data["collector_queue"] <= 1 and data["history_queue"] <= 1
    if "window" in data:
        checks["fixed_workload_input_isolated"] = (
            data["window"]["input_isolated"] and not data["window"]["enabled"]
            and data["window"]["tab"] == 0)
        checks["no_unplanned_inventory"] = not any(data["inventory_rows"].values())
    if checks["completed_for_requested_duration"]:
        # Read-only verification of real worker effects, in the declared private
        # fixture. Never reconcile by executing or restoring anything here.
        from folego.orchestration.journal import Journal
        fixture = Path(data["state"]) / "home"
        original = b'{"startup_boost":{"enabled":true},"soak_fixture":true}'
        checks["fixture_original_bytes_restored"] = (fixture / ".config/microsoft-edge/Local State").read_bytes() == original
        book, problems = Journal(fixture / ".local/state/folego/operations.jsonl").load()
        intents = {record.operation_id: record.plan for record in book if record.kind == "intent"}
        results = {record.operation_id: record.result for record in book if record.kind == "result"}
        checks["journal_complete_and_valid"] = not problems and bool(intents) and intents.keys() == results.keys()
        checks["journal_effects_verified_successfully"] = all(
            result.ok and result.action == intents[identifier].action and
            result.target_key == intents[identifier].target.key
            for identifier, result in results.items() if identifier in intents)
        values["journal_mutations"] = len(intents)
        values["journal_results"] = len(results)
        values["backup_manifests"] = len(list((fixture / ".local/share/folego/backups").rglob("manifest.json")))
        if "job_temp_root" in data:
            root = Path(data["job_temp_root"])
            checks["private_per_attempt_temporaries"] = root == Path(data["state"]) / "general/folego-jobs"
            runs = [run for run in root.iterdir() if run.name.startswith("run-")]
            archive = root / ".retained"
            if archive.exists():
                runs.extend(run for run in archive.iterdir() if run.name.startswith("run-"))
            values["retained_job_runs"] = len(runs)
            checks["retained_run_count_matches_children"] = len(runs) == (
                counters["worker_started"] + counters.get("cancel_started", 0))
            checks["temporary_runs_owned_by_soak"] = all(
                json.loads((run / "run.json").read_text())["launcher_pid"] == data["pid"]
                for run in runs)
    result = {"status": "passed" if all(checks.values()) else "failed",
              "scope": (f"{data['platform']} GUI; synthetic collector; real owned tuning/cancellation children; "
                        f"input isolated: {data.get('window', {}).get('input_isolated', False)}"),
              "values": values, "checks": checks, "policy": policy,
              "source_report": str(args.report), "job_counters": counters}
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
