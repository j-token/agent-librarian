"""Real Codex discovery, opt in with CODEX_E2E_BIN=/absolute/path/codex.exe."""
from collections import deque
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ID = "agent-librarian@agent-librarian"


class CodexAppServer:
    """Only initialize/install/list APIs are used; no thread can execute hooks."""

    def __init__(self, executable, home, workspace):
        self.executable = executable
        self.environment = {**os.environ, "CODEX_HOME": str(home),
                            "HOME": str(home), "USERPROFILE": str(home)}
        self.workspace = workspace
        self.messages = queue.Queue()
        self.stderr = deque(maxlen=30)
        self.request_id = 0

    def __enter__(self):
        self.process = subprocess.Popen(
            [str(self.executable), "app-server", "--stdio"], cwd=self.workspace,
            env=self.environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        )
        self.readers = [threading.Thread(target=self.read_stdout, daemon=True),
                        threading.Thread(target=self.read_stderr, daemon=True)]
        for reader in self.readers:
            reader.start()
        try:
            self.initialized = self.request("initialize", {
                "clientInfo": {"name": "agent_librarian_hooks_e2e", "version": "1"},
                "capabilities": {"experimentalApi": True},
            })
            self.send({"method": "initialized"})
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def read_stdout(self):
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except json.JSONDecodeError:
                    self.messages.put({"readerError": "Codex emitted invalid JSON"})
        finally:
            self.messages.put(None)

    def read_stderr(self):
        for line in self.process.stderr:
            self.stderr.append(line.rstrip())

    def send(self, message):
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        self.process.stdin.flush()

    def request(self, method, params):
        self.request_id += 1
        self.send({"id": self.request_id, "method": method, "params": params})
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                response = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                break
            assert response is not None, f"Codex stdout closed during {method}"
            assert "readerError" not in response, response.get("readerError")
            if response.get("id") == self.request_id:
                assert "error" not in response, f"{method}: {response.get('error')}"
                return response["result"]
        pytest.fail(f"Codex {method} timed out; stderr lines retained: {len(self.stderr)}")

    def __exit__(self, exception_type, *_):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                               capture_output=True, timeout=10, check=False)
            else:
                self.process.kill()
            self.process.wait(timeout=5)
        for reader in self.readers:
            reader.join(timeout=2)
        # Closing a pipe still owned by a blocked reader can wait indefinitely.
        assert all(not reader.is_alive() for reader in self.readers), "Codex readers did not stop"
        for stream in (self.process.stdout, self.process.stderr):
            stream.close()
        if exception_type is None:
            assert self.process.returncode == 0


def test_native_codex_plugin_discovers_three_untrusted_hooks_after_install(tmp_path):
    executable_value = os.environ.get("CODEX_E2E_BIN")
    if not executable_value:
        pytest.skip("Set CODEX_E2E_BIN to an absolute Codex .exe path")
    executable = Path(executable_value)
    assert executable.is_absolute() and executable.suffix.lower() == ".exe"
    assert executable.is_file()

    marketplace = tmp_path / "marketplace"
    shutil.copytree(REPO_ROOT, marketplace, ignore=shutil.ignore_patterns(
        ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"))
    manifest = json.loads((marketplace / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert not (marketplace / "plugin.json").exists(), "Portable manifest takes precedence in Codex"
    assert manifest["name"] == "agent-librarian"
    assert manifest["version"] and manifest["description"]
    assert manifest["hooks"] == "./hooks/hooks.json"

    home = tmp_path / "codex-home"
    workspace = tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    # JSON strings are also TOML basic strings, including escaped Windows paths.
    (home / "config.toml").write_text(
        '[features]\nhooks = true\nplugins = true\nremote_plugin = false\n'
        '[marketplaces.agent-librarian]\nsource_type = "local"\n'
        f"source = {json.dumps(str(marketplace))}\n", encoding="utf-8")
    (home / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{
        "type": "command", "command": "codex-e2e-control-must-never-execute", "timeout": 1,
    }]}]}}), encoding="utf-8")

    with CodexAppServer(executable, home, workspace) as server:
        installation = server.request("plugin/install", {
            "pluginName": "agent-librarian",
            "marketplacePath": str(marketplace / ".claude-plugin" / "marketplace.json"),
        })
        assert installation["appsNeedingAuth"] == []
    # Installation changes config; a fresh server eliminates startup snapshot caching.
    with CodexAppServer(executable, home, workspace) as server:
        hooks_result = server.request("hooks/list", {"cwds": [str(workspace)]})
        plugins_result = server.request("plugin/list", {
            "cwds": [str(workspace)], "forceRefetch": False, "marketplaceKinds": ["local"],
        })
        user_agent = server.initialized["userAgent"]

    entry, = hooks_result["data"]
    plugins = [plugin for catalog in plugins_result["marketplaces"]
               for plugin in catalog["plugins"] if plugin["id"] == PLUGIN_ID]
    hook_fields = ("eventName", "source", "pluginId", "enabled", "trustStatus",
                   "handlerType", "matcher", "timeoutSec", "displayOrder")
    evidence = {
        "userAgent": user_agent, "errors": entry["errors"], "warnings": entry["warnings"],
        "marketplaceLoadErrors": plugins_result["marketplaceLoadErrors"],
        "plugins": [{key: plugin.get(key) for key in
                     ("id", "installed", "enabled", "localVersion")} for plugin in plugins],
        "hooks": [{key: hook.get(key) for key in hook_fields} for hook in entry["hooks"]],
    }
    artifact = tmp_path / "codex-hooks-discovery.json"
    artifact.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    assert entry["errors"] == [] and entry["warnings"] == [], str(artifact)
    assert plugins_result["marketplaceLoadErrors"] == [], str(artifact)
    plugin, = plugins
    assert plugin["installed"] and plugin["enabled"]
    assert plugin["localVersion"] == manifest["version"]

    user_hooks = [hook for hook in entry["hooks"] if hook["source"] == "user"]
    control, = user_hooks
    assert control["eventName"] == "stop" and control["trustStatus"] == "untrusted" and control["enabled"]
    assert control["command"] == "codex-e2e-control-must-never-execute"
    plugin_hooks = [hook for hook in entry["hooks"] if hook["source"] == "plugin"]
    assert len(plugin_hooks) == 3
    hooks_by_event = {hook["eventName"]: hook for hook in plugin_hooks}
    assert set(hooks_by_event) == {"postToolUse", "sessionStart", "stop"}
    assert len(entry["hooks"]) == 4
    assert all(hook["pluginId"] == PLUGIN_ID and hook["enabled"]
               and hook["trustStatus"] == "untrusted" for hook in plugin_hooks)
    assert hooks_by_event["postToolUse"]["timeoutSec"] == 60
    assert hooks_by_event["sessionStart"]["timeoutSec"] == 30
    assert hooks_by_event["stop"]["timeoutSec"] == 120
    assert hooks_by_event["postToolUse"]["matcher"] == "Edit|Write|MultiEdit|apply_patch"
    assert all(hook["handlerType"] == "command" for hook in plugin_hooks)
