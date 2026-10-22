"""Prepare only the local site in this compose project's private volumes."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path("/app")
BENCH = ROOT / ".runtime/bench"
SITES = BENCH / "sites"
SITE = os.environ.get("SCHOOL_SITE_NAME", "school.localhost")
if not SITE or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in SITE):
    raise SystemExit("The local site name must contain only lowercase letters, numbers, dots and hyphens.")
for folder in [SITES, BENCH / "apps", BENCH / "logs"]:
    folder.mkdir(parents=True, exist_ok=True)
for target, source in [
    (BENCH / "env", ROOT / ".venv"),
    (BENCH / "apps/frappe", ROOT / "vendor/framework"),
    (BENCH / "apps/erpnext", ROOT / "vendor/erpnext"),
    (BENCH / "apps/education", ROOT),
]:
    if not target.exists():
        target.symlink_to(source, target_is_directory=True)
(SITES / "apps.txt").write_text("frappe\nerpnext\neducation\n")
(SITES / "common_site_config.json").write_text(json.dumps({
    "db_host": "database", "db_port": 3306, "use_mysqlclient": 0,
    "redis_cache": "redis://cache:6379/0", "redis_queue": "redis://cache:6379/1", "redis_socketio": "redis://cache:6379/2",
    "socketio_port": 9000, "socketio_same_origin": True, "webserver_port": 8000, "webserver_host": "0.0.0.0",
    "default_site": SITE, "serve_default_site": True, "developer_mode": 0, "allow_error_traceback": 0,
    "server_script_enabled": 0, "enable_telemetry": False, "pause_scheduler": False, "disable_scheduler": False,
    "chromium_path": "/usr/bin/chromium",
    "encryption_key": os.environ["SCHOOL_ENCRYPTION_KEY"],
}, indent=2))
(SITES / "common_site_config.json").chmod(0o600)


def bench(*args):
    result = subprocess.run([str(ROOT / ".venv/bin/python"), "-m", "frappe.utils.bench_helper", "frappe", *args], cwd=SITES)
    if result.returncode:
        raise SystemExit("Local site setup did not finish. Check the private container logs.")


config_path = SITES / SITE / "site_config.json"
if not config_path.exists():
    bench("new-site", SITE, "--db-type", "mariadb", "--db-host", "database", "--db-port", "3306",
          "--db-root-password", os.environ["LOCAL_DB_PASSWORD"], "--admin-password", os.environ["SCHOOL_ADMIN_PASSWORD"],
          "--mariadb-user-host-login-scope", "%", "--set-default")
    bench("--site", SITE, "install-app", "erpnext")
    bench("--site", SITE, "install-app", "education")
config = json.loads(config_path.read_text())
config.update(developer_mode=0, allow_error_traceback=0, host_name=f"http://localhost:{os.environ.get('SCHOOL_LOCAL_PORT', '3037')}")
config_path.write_text(json.dumps(config, indent=2)); config_path.chmod(0o600)
assets = SITES / "assets"; assets.mkdir(exist_ok=True)
for name, source in [
    ("education", ROOT / "education/public"),
    ("frappe", ROOT / "vendor/framework/frappe/public"),
    ("erpnext", ROOT / "vendor/erpnext/erpnext/public"),
]:
    link = assets / name
    if not link.exists():
        link.symlink_to(source, target_is_directory=True)
if not (assets / "assets.json").exists():
    # The build's bundle map; without it pages ask for unhashed bundle paths.
    built_map = ROOT / "sites" / "assets" / "assets.json"
    (assets / "assets.json").write_text(built_map.read_text() if built_map.exists() else "{}")
bench("--site", SITE, "migrate")
bench("--site", SITE, "enable-scheduler")
from education.pramaan import PramaanClient
(BENCH / ".outside-configured").write_text("yes" if PramaanClient().configured else "no")
