"""SonarQube-backed static analysis."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import requests

from app import config


_SEVERITY = {
    "BLOCKER": "error",
    "CRITICAL": "error",
    "MAJOR": "warning",
    "MINOR": "refactor",
    "INFO": "info",
}


def configured() -> bool:
    return bool(config.SONAR_URL and (config.SONAR_TOKEN or (
        config.SONAR_USERNAME and config.SONAR_PASSWORD
    )))


def _project_key(workspace: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", Path(workspace).stem).strip("-")
    return (key or "aider-console-workspace")[:200]


def _auth() -> tuple[str, str]:
    if config.SONAR_TOKEN:
        return config.SONAR_TOKEN, ""
    return config.SONAR_USERNAME, config.SONAR_PASSWORD


def _ensure_project(project_key: str, workspace: str) -> None:
    response = requests.post(
        f"{config.SONAR_URL}/api/projects/create",
        auth=_auth(),
        data={"project": project_key, "name": workspace},
        timeout=20,
    )
    if response.status_code in (200, 201):
        return
    if response.status_code == 400 and "exist" in response.text.lower():
        return
    response.raise_for_status()


def _task_id(project_root: Path, output: str) -> str | None:
    for pattern in (
        r"ceTaskId[=:]\s*([a-zA-Z0-9_-]+)",
        r"task\?id=([a-zA-Z0-9_-]+)",
    ):
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return match.group(1)

    report = project_root / ".scannerwork" / "report-task.txt"
    if report.exists():
        for line in report.read_text(errors="replace").splitlines():
            if line.startswith("ceTaskId="):
                return line.split("=", 1)[1].strip()
    return None


def _wait_for_task(task_id: str) -> None:
    deadline = time.monotonic() + config.SONAR_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        response = requests.get(
            f"{config.SONAR_URL}/api/ce/task",
            params={"id": task_id},
            auth=_auth(),
            timeout=20,
        )
        response.raise_for_status()
        status = response.json().get("task", {}).get("status")
        if status == "SUCCESS":
            return
        if status in {"FAILED", "CANCELED"}:
            raise RuntimeError(f"SonarQube analysis task ended with status {status}")
        time.sleep(3)
    raise TimeoutError("Timed out waiting for SonarQube analysis")


def _issues(project_key: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    page = 1
    while True:
        response = requests.get(
            f"{config.SONAR_URL}/api/issues/search",
            params={
                "componentKeys": project_key,
                "resolved": "false",
                "ps": 100,
                "p": page,
            },
            auth=_auth(),
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        result.extend(data.get("issues", []))
        if len(result) >= data.get("total", len(result)):
            return result
        page += 1


def _secure_extract(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute():
                raise RuntimeError(f"Unsafe ZIP entry detected: {member.filename}")
            target = (destination / member_path).resolve()
            if destination not in target.parents and target != destination:
                raise RuntimeError(f"Unsafe ZIP entry detected: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _find_java() -> str | None:
    candidates = [
        config.JAVA_EXE,
        os.environ.get("JAVA_HOME", ""),
        shutil.which("java") or "",
        "/usr/bin/java",
        "/usr/local/bin/java",
    ]
    for candidate in candidates:
        executable = Path(candidate)
        if executable.name == "JAVA_HOME":
            executable /= "bin/java"
        if executable.is_file() and os.access(executable, os.X_OK):
            return str(executable)
    return None


def analyze_workspace(
    workspace: str, project_root: Path, files: list[str]
) -> list[dict[str, Any]]:
    if not configured():
        raise RuntimeError(
            "SonarQube is not configured; set SONAR_URL and SONAR_TOKEN "
            "(or SONAR_USERNAME/SONAR_PASSWORD)"
        )

    scanner = shutil.which(config.SONAR_SCANNER)
    if not scanner and Path(config.SONAR_SCANNER).is_file():
        scanner = str(Path(config.SONAR_SCANNER).resolve())
    if not scanner:
        raise RuntimeError(
            f"SonarScanner not found: {config.SONAR_SCANNER}. "
            "Install SonarScanner CLI or set SONAR_SCANNER to its full path."
        )

    java_exe = _find_java()
    if not java_exe:
        raise RuntimeError("Java executable was not found. Install Java or configure JAVA_HOME.")

    project_key = _project_key(workspace)
    _ensure_project(project_key, workspace)

    with tempfile.TemporaryDirectory(prefix="aider-sonar-") as temp_dir:
        staging = Path(temp_dir) / "project"
        archive = Path(temp_dir) / "project.zip"
        root = project_root.resolve()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename in files:
                source = (root / filename).resolve()
                if root not in source.parents or not source.is_file():
                    raise RuntimeError(f"Analysis file not found: {filename}")
                zf.write(source, Path(filename).as_posix())
        _secure_extract(archive, staging)

        command = [
            scanner,
            f"-Dsonar.host.url={config.SONAR_URL}",
            f"-Dsonar.projectKey={project_key}",
            "-Dsonar.sources=.",
            f"-Dsonar.inclusions={','.join(Path(f).as_posix() for f in files)}",
            "-Dsonar.sourceEncoding=UTF-8",
            "-Dsonar.scanner.skipJreProvisioning=true",
            f"-Dsonar.scanner.javaExePath={java_exe}",
            "-Dsonar.scanner.connectTimeout=15",
            "-Dsonar.scanner.socketTimeout=120",
            "-Dsonar.scanner.responseTimeout=120",
            "-Dsonar.verbose=true",
        ]
        if config.SONAR_TOKEN:
            command.append(f"-Dsonar.login={config.SONAR_TOKEN}")
        else:
            command.extend([
                f"-Dsonar.login={config.SONAR_USERNAME}",
                f"-Dsonar.password={config.SONAR_PASSWORD}",
            ])

        env = os.environ.copy()
        env["SONAR_HOST_URL"] = config.SONAR_URL
        env["SONAR_SCANNER_SKIP_JRE_PROVISIONING"] = "true"
        env["SONAR_SCANNER_JAVA_EXE_PATH"] = java_exe

        process = subprocess.run(
            command,
            cwd=staging,
            env=env,
            capture_output=True,
            text=True,
            timeout=config.SONAR_TIMEOUT_SECONDS,
        )
        output = f"{process.stdout}\n{process.stderr}"
        if process.returncode != 0:
            raise RuntimeError(output.strip() or "SonarScanner failed")

        task_id = _task_id(staging, output)
        if not task_id:
            raise RuntimeError("SonarScanner completed without a Compute Engine task id")
        _wait_for_task(task_id)

    normalized = []
    allowed = {Path(filename).as_posix() for filename in files}
    for issue in _issues(project_key):
        filename = issue.get("component", "").split(":", 1)[-1].lstrip("/\\")
        if filename not in allowed:
            continue
        normalized.append({
            "file": filename,
            "line": max(1, int(issue.get("line") or 1)),
            "column": max(0, int(issue.get("textRange", {}).get("startLineOffset") or 0)),
            "severity": _SEVERITY.get(issue.get("severity", "INFO"), "info"),
            "rule": issue.get("rule", "sonar"),
            "message": issue.get("message", ""),
            "tool": "sonarqube",
        })
    return normalized
