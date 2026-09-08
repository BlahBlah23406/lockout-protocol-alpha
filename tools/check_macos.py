"""Structural sanity check for the macOS Swift sources. Run from the repo root.

Not a compiler — there is no Swift toolchain on this machine. It catches the two classes of
mistake that a hand-written port actually makes: unbalanced delimiters (usually a botched string
edit) and references to symbols that do not exist anywhere in the target.
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "macos")
files = sorted(root.rglob("*.swift"))

def strip_noise(text):
    """Remove comments and string literals so delimiter counting isn't fooled by them."""
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            # Multi-line string literal
            if text[i:i + 3] == '"""':
                end = text.find('"""', i + 3)
                i = n if end == -1 else end + 3
                continue
            i += 1
            while i < n:
                if text[i] == "\\":
                    # An interpolation \( ... ) contains real code; keep its delimiters balanced
                    # by emitting them.
                    if text[i + 1:i + 2] == "(":
                        depth = 0
                        j = i + 1
                        while j < n:
                            if text[j] == "(":
                                depth += 1
                            elif text[j] == ")":
                                depth -= 1
                                if depth == 0:
                                    break
                            j += 1
                        i = j + 1
                        continue
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if text[i:i + 2] == "//":
            end = text.find("\n", i)
            i = n if end == -1 else end
            continue
        if text[i:i + 2] == "/*":
            end = text.find("*/", i)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)

problems = []
all_text = "\n".join(f.read_text(encoding="utf-8") for f in files)

for f in files:
    text = f.read_text(encoding="utf-8")
    code = strip_noise(text)
    for open_c, close_c, label in (("{", "}", "braces"), ("(", ")", "parens"),
                                   ("[", "]", "brackets")):
        diff = code.count(open_c) - code.count(close_c)
        if diff:
            problems.append(f"{f}: unbalanced {label} ({diff:+d})")
    if text.count('"""') % 2:
        problems.append(f"{f}: odd number of \"\"\" multi-line string delimiters")

# Symbols the new focus code leans on. A typo here is a build break on a Mac we can't test on.
required = [
    "enum LCARS", "struct LcarsButton", "struct LcarsHeader", "struct ReadoutPanel",
    "enum ScreenState", "enum FrameQuality", "enum ScreenCapturer", "enum Overrides",
    "enum Pusher", "final class EventLog", "enum InstalledApps", "enum TamperAlert",
    "enum FrontmostApp", "final class Prefs", "struct AppSelectList",
    # new in this change
    "enum Accountability", "struct FocusSession", "final class SessionStore",
    "enum Providers", "enum Judgements", "enum LearnedPolicy", "struct FocusStartForm",
]
for symbol in required:
    if symbol not in all_text:
        problems.append(f"MISSING declaration: {symbol}")

# Members referenced by the new code that must exist on the old types.
members = [
    ("Prefs", ["var monitoredApps", "var dryRun", "var pinSet", "func checkPin",
               "var ntfyTopic", "var pushEnabled", "var ntfyServer",
               "var alertOnUnverifiable", "var closeUnverifiable", "var monitoringEnabled",
               "var lastViolationAt", "var apiKeys", "func promoteApiKey"]),
    ("ScreenState", ["static var isVisible", "static var reason"]),
    ("FrameQuality", ["static func isUnreadable"]),
    ("ScreenCapturer", ["static func capture", "static func hasPermission"]),
    ("Overrides", ["static func isActive", "static func grant"]),
    ("FrontmostApp", ["static var bundleId", "static func shortName", "static func hide",
                      "static func quit", "static func windowTitle"]),
]
for owner, needed in members:
    for member in needed:
        if member not in all_text:
            problems.append(f"MISSING member on {owner}: {member}")

print(f"scanned {len(files)} Swift files")
for p in problems:
    print("  !", p)
print("\nSTRUCTURE OK" if not problems else f"\n{len(problems)} PROBLEM(S)")
sys.exit(1 if problems else 0)
