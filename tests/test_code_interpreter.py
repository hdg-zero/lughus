"""Confinement contract tests; no container daemon required."""

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lughus.core.binary_artifacts import FileArtifactStore
from lughus.engine.interpreter import (
    ContainerConfig,
    ContainerPythonBackend,
    SandboxUnavailableError,
)

IMAGE = "python@sha256:" + "a" * 64


class InterpreterTests(unittest.TestCase):
    def test_requires_pinned_image(self) -> None:
        with self.assertRaises(ValueError):
            ContainerConfig("python:latest")

    def test_missing_engine_fails_closed(self) -> None:
        with patch("shutil.which", return_value=None), self.assertRaises(SandboxUnavailableError):
            ContainerPythonBackend(ContainerConfig(IMAGE)).command("test")

    def test_confinement_flags(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/docker"):
            command = ContainerPythonBackend(ContainerConfig(IMAGE)).command("test")
        for flag in (
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--pull=never",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
        ):
            self.assertIn(flag, command)
        self.assertNotIn("--privileged", command)
        self.assertNotIn("--volume", command)

    def test_artifacts_survive_execution_result(self) -> None:
        envelope = {
            "stdout": "ok",
            "stderr": "",
            "exit_code": 0,
            "files": [{"name": "out.txt", "data": base64.b64encode(b"hello").decode()}],
        }
        result = ContainerPythonBackend(ContainerConfig(IMAGE))._decode(
            json.dumps(envelope).encode()
        )
        with tempfile.TemporaryDirectory() as directory:
            ref = FileArtifactStore(directory).put(result.files[0])
            self.assertEqual((Path(directory) / ref.artifact_id).read_bytes(), b"hello")

    def test_rejects_traversal_and_oversized_data(self) -> None:
        backend = ContainerPythonBackend(ContainerConfig(IMAGE, max_artifact_bytes=2))
        for name, data in (("../escape", "YQ=="), ("/absolute", "YQ=="), ("a", "YWJj")):
            envelope = {
                "stdout": "",
                "stderr": "",
                "exit_code": 0,
                "files": [{"name": name, "data": data}],
            }
            with self.assertRaises(ValueError):
                backend._decode(json.dumps(envelope).encode())
