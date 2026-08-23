import atexit
import json
import os
import re
import subprocess
import threading
import time
import uuid
from collections import deque


class GatewaySessionError(RuntimeError):
    pass


class GatewayPowerShellSession:
    """Owns the isolated PowerShell process used for gateway administration."""

    RESULT_PREFIX = "@@GATEWAY_RESULT@@"
    READY_MARKER = "@@GATEWAY_READY@@"
    ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

    def __init__(self, script_path):
        self.script_path = script_path
        self.process = None
        self.reader_thread = None
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.results = {}
        self.logs = deque(maxlen=120)
        self.ready = False
        self.busy = False
        self.current_operation = None
        self.current_request_id = None
        self.azure_connected = False
        self.gateway_connected = False
        self.last_error = None
        atexit.register(self.close)

    def _start(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                return

            self._reset_runtime_state()
            self.process = subprocess.Popen(
                [
                    "pwsh",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    self.script_path,
                ],
                cwd=os.path.dirname(self.script_path),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            self.reader_thread = threading.Thread(
                target=self._read_output,
                name="gateway-powershell-reader",
                daemon=True,
            )
            self.reader_thread.start()

            deadline = time.monotonic() + 60
            while not self.ready and self.process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(remaining)

            if not self.ready:
                detail = self.last_error or "PowerShell host did not become ready."
                self.close()
                raise GatewaySessionError(detail)

    def _reset_runtime_state(self):
        self.ready = False
        self.busy = False
        self.current_operation = None
        self.current_request_id = None
        self.azure_connected = False
        self.gateway_connected = False
        self.last_error = None
        self.results.clear()
        self.logs.clear()

    def _read_output(self):
        process = self.process
        if not process or not process.stdout:
            return

        for raw_line in process.stdout:
            line = self.ANSI_ESCAPE.sub("", raw_line.rstrip("\r\n"))
            with self.condition:
                if line == self.READY_MARKER:
                    self.ready = True
                    self.condition.notify_all()
                    continue

                if line.startswith(self.RESULT_PREFIX):
                    payload_text = line[len(self.RESULT_PREFIX):]
                    try:
                        payload = json.loads(payload_text)
                    except json.JSONDecodeError:
                        self.last_error = "PowerShell returned an invalid response."
                        self.logs.append(line)
                        self.condition.notify_all()
                        continue

                    request_id = payload.get("requestId")
                    if request_id:
                        self.results[request_id] = payload
                    self._apply_connection_result(payload)
                    if request_id == self.current_request_id:
                        self.busy = False
                        self.current_operation = None
                        self.current_request_id = None
                    if not payload.get("ok"):
                        self.last_error = payload.get("error") or "Gateway operation failed."
                    else:
                        self.last_error = None
                    self.condition.notify_all()
                    continue

                if line:
                    self.logs.append(line)
                    self.condition.notify_all()

        with self.condition:
            if self.process is not process:
                return
            if process.poll() not in (None, 0):
                self.last_error = f"PowerShell host exited with code {process.returncode}."
            self.ready = False
            self.busy = False
            self.azure_connected = False
            self.gateway_connected = False
            self.condition.notify_all()

    def _apply_connection_result(self, payload):
        operation = payload.get("operation")
        if operation == "connect_azure":
            self.azure_connected = bool(payload.get("ok"))
        elif operation == "connect_gateway":
            self.gateway_connected = bool(payload.get("ok"))
        elif operation == "disconnect" and payload.get("ok"):
            self.azure_connected = False
            self.gateway_connected = False
        elif operation == "connection_status" and payload.get("ok"):
            data = payload.get("data") or {}
            self.azure_connected = bool(data.get("azureConnected"))
            self.gateway_connected = bool(data.get("gatewayConnected"))

    def start_async(self, operation, **parameters):
        self._start()
        with self.condition:
            if self.busy:
                raise GatewaySessionError(
                    f"Gateway session is busy with '{self.current_operation}'."
                )
            request_id = self._send(operation, parameters)
            return request_id

    def execute(self, operation, timeout=60, **parameters):
        request_id = self.start_async(operation, **parameters)
        deadline = time.monotonic() + timeout
        with self.condition:
            while request_id not in self.results:
                if not self.process or self.process.poll() is not None:
                    raise GatewaySessionError(
                        self.last_error or "PowerShell host stopped unexpectedly."
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise GatewaySessionError(
                        f"Gateway operation '{operation}' timed out."
                    )
                self.condition.wait(remaining)

            result = self.results.pop(request_id)

        if not result.get("ok"):
            raise GatewaySessionError(result.get("error") or "Gateway operation failed.")
        return result.get("data")

    def _send(self, operation, parameters):
        if not self.process or self.process.poll() is not None or not self.process.stdin:
            raise GatewaySessionError("PowerShell host is not running.")

        request_id = uuid.uuid4().hex
        command = {
            "requestId": request_id,
            "operation": operation,
            "parameters": parameters,
        }
        self.busy = True
        self.current_operation = operation
        self.current_request_id = request_id
        self.logs.clear()
        try:
            self.process.stdin.write(json.dumps(command) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self.busy = False
            self.current_operation = None
            self.current_request_id = None
            raise GatewaySessionError("Could not communicate with PowerShell.") from exc
        return request_id

    def snapshot(self):
        with self.lock:
            running = bool(self.process and self.process.poll() is None)
            return {
                "running": running,
                "ready": self.ready,
                "busy": self.busy,
                "operation": self.current_operation,
                "azureConnected": self.azure_connected,
                "gatewayConnected": self.gateway_connected,
                "logs": list(self.logs),
                "lastError": self.last_error,
            }

    def close(self):
        with self.lock:
            process = self.process
            self.process = None
            if not process:
                return
            if process.poll() is None:
                try:
                    if process.stdin:
                        process.stdin.write(
                            json.dumps(
                                {
                                    "requestId": uuid.uuid4().hex,
                                    "operation": "exit",
                                    "parameters": {},
                                }
                            )
                            + "\n"
                        )
                        process.stdin.flush()
                        process.wait(timeout=3)
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
            self._reset_runtime_state()
