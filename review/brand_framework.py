"""Remove inherited desktop support actions from the pinned framework at build time."""
from pathlib import Path
import re
import sys


def school_desktop(source):
    start = source.index("\tsetup_avatar() {")
    end = source.index("\n\tsetup_navbar()", start)
    avatar = source[start:end]
    marker = "// School desktop menu: local account actions only."
    if marker in avatar:
        return source
    pattern = r'\n\t{3}\{\n\t{4}icon: "(?:info|life-buoy)",.*?\n\t{4}order: (?:30|40),\n\t{3}\},'
    avatar, count = re.subn(pattern, "", avatar, flags=re.S)
    if count != 2:
        raise ValueError("The pinned desktop menu changed; review its support actions before building.")
    avatar = avatar.replace("\tsetup_avatar() {", "\tsetup_avatar() {\n\t\t" + marker, 1)
    return source[:start] + avatar + source[end:]


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("vendor/framework")
    path = root / "frappe/desk/page/desktop/desktop.js"
    path.write_text(school_desktop(path.read_text()))
