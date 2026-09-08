"""Structural sanity check for the iOS sources.

There is no Swift toolchain and no Xcode on this machine, so this cannot be a compile. It checks
what a text tool honestly can: balanced delimiters (which catches a botched string edit), that
every declaration the code references actually exists somewhere in the target, and — the part that
matters most on iOS — that the App Group and bundle identifiers agree everywhere they are written
down. Those identifiers are duplicated across five entitlements files, five plists, the project
spec, and two Swift constants, and every mismatch fails silently at runtime.
"""
import plistlib
import re
import sys
from pathlib import Path

root = Path("ios")
problems = []

# ---- 1. Swift delimiters + declarations ----------------------------------------------------

files = sorted(root.rglob("*.swift"))
all_text = "\n".join(f.read_text(encoding="utf-8") for f in files)


def strip_noise(text):
    """Remove comments and string literals so delimiter counting isn't fooled by them."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == '"':
            if text[i:i + 3] == '"""':
                end = text.find('"""', i + 3)
                i = n if end == -1 else end + 3
                continue
            i += 1
            while i < n:
                if text[i] == "\\":
                    if text[i + 1:i + 2] == "(":          # interpolation contains real code
                        depth, j = 0, i + 1
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
        out.append(text[i])
        i += 1
    return "".join(out)


for f in files:
    text = f.read_text(encoding="utf-8")
    code = strip_noise(text)
    for opener, closer, label in (("{", "}", "braces"), ("(", ")", "parens"),
                                  ("[", "]", "brackets")):
        diff = code.count(opener) - code.count(closer)
        if diff:
            problems.append(f"{f}: unbalanced {label} ({diff:+d})")
    if text.count('"""') % 2:
        problems.append(f'{f}: odd number of """ delimiters')

required = [
    "enum Accountability", "struct FocusSession", "final class SessionStore", "enum SharedSession",
    "enum ShieldPlan", "enum Providers", "enum ProviderKind", "struct ProviderPreset",
    "final class ShieldController", "enum Keychain", "enum Judgements", "enum Pusher",
    "final class Prefs", "struct LockoutApp", "struct RootView", "struct FocusStartView",
    "struct SettingsView", "struct FocusWidget", "class ShieldConfigurationExtension",
    "class ShieldActionExtension", "class DeviceActivityMonitorExtension",
]
for symbol in required:
    if symbol not in all_text:
        problems.append(f"MISSING declaration: {symbol}")

# Things the iOS code calls on its own types.
members = [
    "static let appGroup", "static func containerDirectory", "static var containerIsShared",
    "func apply(tokens:", "func clear()", "func unshield(token:", "func schedule(until end:",
    "func diagnose()", "static func encode(token:", "static func decode(tokens:",
    "static func decide(task:", "static func completeText(", "static func reachability(",
    "func providerConfig()", "static func recordSessionStart(", "static func drainSpool()",
]
for member in members:
    if member not in all_text:
        problems.append(f"MISSING member: {member}")

# The iOS port must NOT contain a screen capture path. If one ever appears it is either dead code
# or a private API, and both are worth failing over.
for banned, why in (("ScreenCaptureKit", "iOS has no ScreenCaptureKit"),
                    ("CGWindowListCopyWindowInfo", "not available to iOS apps"),
                    ("UIGraphicsImageRenderer(bounds", "would only capture our own window")):
    if banned in all_text:
        problems.append(f"BANNED on iOS: {banned} — {why}")

# ---- 2. Identifier agreement ---------------------------------------------------------------

APP_GROUP = "group.com.lockoutprotocol.lockout"

# Every entitlements file must name the App Group.
for ent in sorted(root.rglob("*.entitlements")):
    with open(ent, "rb") as fh:
        data = plistlib.load(fh)
    groups = data.get("com.apple.security.application-groups", [])
    if APP_GROUP not in groups:
        problems.append(f"{ent}: App Group {APP_GROUP} missing (found {groups})")

# The Swift constant must match.
swift_group = re.search(r'static let appGroup = "([^"]+)"', all_text)
if not swift_group:
    problems.append("SessionStore.appGroup not found")
elif swift_group.group(1) != APP_GROUP:
    problems.append(f"SessionStore.appGroup is {swift_group.group(1)}, entitlements say {APP_GROUP}")

# Anywhere else the group is hardcoded (the monitor extension duplicates it deliberately).
for hit in set(re.findall(r'forSecurityApplicationGroupIdentifier: "([^"]+)"', all_text)):
    if hit != APP_GROUP:
        problems.append(f"hardcoded App Group mismatch: {hit}")

# The named ManagedSettingsStore must be identical in the controller and the action extension,
# or an unshield would edit a different store than the one holding the shield.
store_names = set(re.findall(r'ManagedSettingsStore\.Name\("([^"]+)"\)', all_text))
if len(store_names) > 1:
    problems.append(f"ManagedSettingsStore names disagree: {sorted(store_names)}")

# Extension principal classes must exist in Swift.
for plist in sorted(root.rglob("Info.plist")):
    with open(plist, "rb") as fh:
        data = plistlib.load(fh)
    ext = data.get("NSExtension", {})
    principal = ext.get("NSExtensionPrincipalClass", "")
    if principal:
        cls = principal.split(".")[-1]
        if f"class {cls}" not in all_text:
            problems.append(f"{plist}: principal class {cls} not found in Swift")
    point = ext.get("NSExtensionPointIdentifier", "")
    if plist.parent.name != "Lockout" and not point:
        problems.append(f"{plist}: no NSExtensionPointIdentifier")

# Every target in project.yml must have the plist and entitlements it names.
spec = (root / "project.yml").read_text(encoding="utf-8")
for match in re.finditer(r"INFOPLIST_FILE: (\S+)", spec):
    if not (root / match.group(1)).exists():
        problems.append(f"project.yml names a missing plist: {match.group(1)}")
for match in re.finditer(r"CODE_SIGN_ENTITLEMENTS: (\S+)", spec):
    if not (root / match.group(1)).exists():
        problems.append(f"project.yml names missing entitlements: {match.group(1)}")

# Every Swift file must belong to some target's sources.
listed = set()
for match in re.finditer(r"- path: (\S+)", spec):
    listed.add(match.group(1))
for f in files:
    rel = f.relative_to(root).as_posix()
    if rel in listed:
        continue
    if any(rel.startswith(prefix + "/") for prefix in listed):
        continue
    problems.append(f"not in any target's sources: {rel}")

print(f"scanned {len(files)} Swift files, "
      f"{len(list(root.rglob('*.entitlements')))} entitlements, "
      f"{len(list(root.rglob('Info.plist')))} plists")
for p in problems:
    print("  !", p)
print("\niOS STRUCTURE OK" if not problems else f"\n{len(problems)} PROBLEM(S)")
sys.exit(1 if problems else 0)
