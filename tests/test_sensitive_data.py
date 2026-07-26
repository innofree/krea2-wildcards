from __future__ import annotations

from pathlib import Path

from check_sensitive_data import scan_text


def test_sensitive_scanner_detects_runtime_built_private_address_and_account() -> None:
    private_address = ".".join(str(part) for part in (10, 20, 30, 40))
    account_name = Path.home().name
    findings = scan_text(
        f"http://{private_address}:8188 /home/{account_name}/service {account_name}@host.example",
        account_name,
    )
    assert findings == {
        "IP address literal",
        "account home path",
        "account-at-host identifier",
        "local account name",
    }


def test_sensitive_scanner_allows_documentation_placeholders() -> None:
    text = "<SSH_USER>@<COMFYUI_HOST> <REMOTE_COMFYUI_ROOT>/models/wildcards"
    assert scan_text(text, Path.home().name) == set()
