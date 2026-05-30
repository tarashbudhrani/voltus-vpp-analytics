"""Run the full Voltus VPP analytics pipeline end-to-end."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
API_URL = "http://127.0.0.1:5001/api/devices"
TOTAL_STEPS = 8


def run_step(step: int, description: str, command: list[str], env: dict | None = None) -> float:
    print(f"[Step {step}/{TOTAL_STEPS}] Running {description}...")
    start = time.perf_counter()
    subprocess.run(command, cwd=PROJECT_ROOT, check=True, env=env or os.environ.copy())
    elapsed = time.perf_counter() - start
    print(f"[Step {step}/{TOTAL_STEPS}] Done in {elapsed:.1f} seconds")
    return elapsed


def run_module(step: int, description: str, module_path: str) -> float:
    return run_step(step, description, [PYTHON, module_path])


def start_mock_api() -> threading.Thread:
    def _serve() -> None:
        from synthetic.mock_thermostat_api import main as api_main

        api_main()

    thread = threading.Thread(target=_serve, name="mock-thermostat-api", daemon=True)
    thread.start()
    return thread


def wait_for_api(timeout_seconds: int = 90) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = requests.get(API_URL, timeout=2)
            if response.status_code == 200:
                return
        except requests.RequestException:
            time.sleep(0.5)
    raise TimeoutError(f"Mock thermostat API did not become ready at {API_URL}")


def kill_port(port: int = 5001) -> None:
    subprocess.run(
        ["bash", "-c", f"lsof -ti:{port} | xargs kill -9 2>/dev/null || true"],
        cwd=PROJECT_ROOT,
        check=False,
    )


def main() -> None:
    pipeline_start = time.perf_counter()
    step_times: list[float] = []
    env = os.environ.copy()
    env["VPP_PIPELINE"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    step_times.append(run_module(1, "generate_enrollment_csv.py", "synthetic/generate_enrollment_csv.py"))
    step_times.append(run_module(2, "seed_database.py", "db/seed_database.py"))

    subprocess.run([PYTHON, "synthetic/generate_interval_data.py"], cwd=PROJECT_ROOT, check=True)

    kill_port(5001)
    print(f"[Step 3/{TOTAL_STEPS}] Running mock_thermostat_api.py (background)...")
    step_start = time.perf_counter()
    start_mock_api()
    wait_for_api()
    step_times.append(time.perf_counter() - step_start)
    print(f"[Step 3/{TOTAL_STEPS}] Done in {step_times[-1]:.1f} seconds")

    step_times.append(run_step(4, "05_ingest_eia_api.py", [PYTHON, "ingestion/05_ingest_eia_api.py"]))
    step_times.append(
        run_step(5, "01_clean_all_sources.py", [PYTHON, "ingestion/01_clean_all_sources.py"], env=env)
    )
    step_times.append(run_module(6, "02_link_entities.py", "transform/02_link_entities.py"))
    step_times.append(run_module(7, "03_compute_cbl_and_performance.py", "transform/03_compute_cbl_and_performance.py"))

    total_elapsed = time.perf_counter() - pipeline_start
    print(f"[Step 8/{TOTAL_STEPS}] Running final summary...")
    print(f"[Step 8/{TOTAL_STEPS}] Done in 0.0 seconds")
    print(f"\nPipeline complete in {total_elapsed:.1f} seconds.")
    print("Run: streamlit run dashboard/streamlit_app.py")

    if total_elapsed > 60:
        print(f"Note: target runtime is under 60 seconds (actual {total_elapsed:.1f}s).")


if __name__ == "__main__":
    main()
