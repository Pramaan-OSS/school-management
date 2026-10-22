"""Generate private local settings without displaying their values."""
from pathlib import Path
import base64
import re
import secrets
import sys


def configure(root, port=None, server_mode=None):
    root = Path(root)
    target = root / ".env"
    text = (target if target.exists() else root / ".env.example").read_text()
    defaults = {
        "LOCAL_DB_PASSWORD": secrets.token_hex(24),
        "SCHOOL_ADMIN_PASSWORD": secrets.token_urlsafe(24),
        "SCHOOL_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "SCHOOL_SITE_NAME": "school.localhost",
        "SCHOOL_LOCAL_PORT": "3037",
        "SCHOOL_COMPOSE_PROJECT": "school-" + secrets.token_hex(6),
    }
    for name, default in defaults.items():
        match = re.search(rf"^{name}=(.*)$", text, re.M)
        if match and match[1].strip().strip("\"'"):
            continue
        line = f"{name}={default}"
        text = re.sub(rf"^{name}=.*$", lambda _: line, text, flags=re.M) if match else text.rstrip() + "\n" + line + "\n"
    if port is not None:
        if not str(port).isdigit() or not 1024 <= int(port) <= 65535:
            raise ValueError("Choose a valid local port.")
        text = re.sub(r"^SCHOOL_LOCAL_PORT=.*$", f"SCHOOL_LOCAL_PORT={port}", text, flags=re.M)
    if server_mode is not None:
        if server_mode not in {"development", "production"}:
            raise ValueError("Choose development or production server mode.")
        line = f"SCHOOL_SERVER_MODE={server_mode}"
        text = re.sub(r"^SCHOOL_SERVER_MODE=.*$", line, text, flags=re.M) if re.search(r"^SCHOOL_SERVER_MODE=", text, re.M) else text.rstrip() + "\n" + line + "\n"
    target.write_text(text)
    target.chmod(0o600)
    runtime = root / ".runtime"
    runtime.mkdir(exist_ok=True)
    credential = runtime / "local-admin-password"
    credential.write_text(re.search(r"^SCHOOL_ADMIN_PASSWORD=(.*)$", text, re.M)[1] + "\n")
    credential.chmod(0o600)
    print("Local settings are saved in .env. The Administrator password is in .runtime/local-admin-password; keep both files private.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--print-port":
        print(re.search(r"^SCHOOL_LOCAL_PORT=(\d+)$", Path(".env").read_text(), re.M)[1])
    else:
        configure(
            Path.cwd(),
            port=sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--port" else None,
            server_mode=sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--server-mode" else None,
        )
