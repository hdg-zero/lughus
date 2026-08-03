from lughus.domain import RunEvent
from lughus.replay import ReplayBundle, ReplayCapturePolicy


def test_replay_capture_policy_redacts_nested_secrets():
    assert ReplayCapturePolicy().sanitize({"token": "abc", "x": {"password": "p"}}) == {
        "token": "[REDACTED]",
        "x": {"password": "[REDACTED]"},
    }


def test_replay_signature_authenticates_digest():
    bundle = ReplayBundle("0.10.0", "run", {}, (RunEvent("done", "run", 0),)).seal(
        signing_key=b"key"
    )
    assert bundle.verify_signature(b"key") and not bundle.verify_signature(b"other")
