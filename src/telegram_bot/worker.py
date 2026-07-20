"""Controlled lifecycle management for the standalone Telegram bot process."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .config import load_telegram_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = PROJECT_ROOT / "user_database" / "telegram_bot_worker.json"
LOG_PATH = PROJECT_ROOT / "output" / "telegram-bot" / "telegram_bot.log"


@dataclass(frozen=True)
class WorkerStatus:
    running: bool
    pid: int | None
    message: str


class TelegramWorkerManager:
    """Start and stop only a verified SAIP Telegram worker process."""

    def __init__(self, state_path: Path = STATE_PATH, log_path: Path = LOG_PATH):
        self.state_path = state_path
        self.log_path = log_path

    def status(self) -> WorkerStatus:
        state = self._read_state()
        if not state:
            return WorkerStatus(False, None, "Stopped")
        try:
            pid = int(state["pid"])
        except (KeyError, TypeError, ValueError):
            self._clear_state()
            return WorkerStatus(False, None, "Stopped")
        if self._is_saip_worker(pid):
            return WorkerStatus(True, pid, "Running")
        self._clear_state()
        return WorkerStatus(False, None, "Stopped")

    def start(self) -> WorkerStatus:
        current = self.status()
        if current.running:
            return current
        # Fail before creating a process if an admin has not configured the bot.
        load_telegram_config()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                [sys.executable, "-m", "src.telegram_bot.main"],
                cwd=PROJECT_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self._write_state(process.pid)
        # Let a configuration/import error surface before the admin UI reports success.
        time.sleep(0.25)
        if process.poll() is not None:
            self._clear_state()
            return WorkerStatus(False, None, "Worker exited during startup. Open the recent worker log for details.")
        return WorkerStatus(True, process.pid, "Running")

    def stop(self) -> WorkerStatus:
        return self._stop(force=False)

    def restart_active_worker(self) -> WorkerStatus:
        """Force-restart the worker so a stuck active job is retried or removed."""
        if self.status().running:
            stopped = self._stop(force=True)
            if stopped.running:
                return stopped
        return self.start()

    def _stop(self, *, force: bool) -> WorkerStatus:
        current = self.status()
        if not current.running or current.pid is None:
            return WorkerStatus(False, None, "Already stopped")
        # status() verified the process command before this signal is sent.
        os.kill(current.pid, signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.1)
            if not self._is_saip_worker(current.pid):
                self._clear_state()
                return WorkerStatus(False, None, "Stopped")
        if force and self._is_saip_worker(current.pid):
            # asyncio.to_thread cannot safely stop a synchronous model call.
            # The queue permits only one running job, so force-ending this
            # verified worker is the bounded way to cancel that one request.
            os.kill(current.pid, signal.SIGKILL)
            for _ in range(20):
                time.sleep(0.1)
                if not self._is_saip_worker(current.pid):
                    self._clear_state()
                    return WorkerStatus(False, None, "Stopped")
        return WorkerStatus(True, current.pid, "Stopping — refresh in a moment")

    def register_current_process(self) -> None:
        """Make a manually started worker visible to the SAIP Admin page too."""
        self._write_state(os.getpid())

    def unregister_current_process(self) -> None:
        state = self._read_state()
        if state and state.get("pid") == os.getpid():
            self._clear_state()

    def recent_log(self, lines: int = 80) -> str:
        if not self.log_path.is_file():
            return "No worker log has been created yet."
        content = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(content[-lines:]) or "No worker output yet."

    def _is_saip_worker(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            command = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return False
        return "src.telegram_bot.main" in command

    def _read_state(self) -> dict | None:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _write_state(self, pid: int) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.state_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps({"pid": pid}), encoding="utf-8")
        temporary_path.replace(self.state_path)

    def _clear_state(self) -> None:
        try:
            self.state_path.unlink()
        except FileNotFoundError:
            pass
