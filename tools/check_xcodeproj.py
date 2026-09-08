"""Validate the committed macOS pbxproj. Run from the repo root.

Xcode's project format has no schema and fails at open time with unhelpful errors, so this checks
the invariants that actually matter: every referenced object id resolves, every Swift source on
disk is compiled by some target, and the delimiter structure is intact.
"""
import re
import sys
from pathlib import Path

PBX = Path("macos/Guardian.xcodeproj/project.pbxproj")
text = PBX.read_text(encoding="utf-8")
problems = []

# 1. Structure.
if text.count("{") != text.count("}"):
    problems.append(f"unbalanced braces ({text.count('{')} open, {text.count('}')} close)")
if text.count("(") != text.count(")"):
    problems.append(f"unbalanced parens ({text.count('(')} open, {text.count(')')} close)")
for section in ("PBXBuildFile", "PBXFileReference", "PBXGroup", "PBXSourcesBuildPhase",
                "PBXNativeTarget", "PBXProject"):
    if text.count(f"/* Begin {section} section */") != 1:
        problems.append(f"{section}: expected exactly one Begin marker")
    if text.count(f"/* End {section} section */") != 1:
        problems.append(f"{section}: expected exactly one End marker")

# 2. Every id referenced anywhere must be declared somewhere.
declared_list = re.findall(r"^\t\t([0-9A-F]{24}) /\*.*?\*/ = \{", text, re.M)
declared = set(declared_list)
referenced = set(re.findall(r"([0-9A-F]{24}) /\*", text))
dangling = referenced - declared
if dangling:
    problems.append(f"{len(dangling)} id(s) referenced but never declared: "
                    + ", ".join(sorted(dangling)[:5]))

# 3. Duplicate declarations would make Xcode pick one arbitrarily.
dupes = {i for i in declared_list if declared_list.count(i) > 1}
if dupes:
    problems.append(f"duplicate object ids: {sorted(dupes)}")

# 4. Every Swift file must be compiled by SOME target. Both the app and the test bundle have a
#    phase literally named "Sources", so all of them are collected rather than guessing which is
#    which — a file compiled by either is a file that will build.
phases = re.findall(r"isa = PBXSourcesBuildPhase;.*?files = \((.*?)\);", text, re.S)
compiled = set()
for phase in phases:
    compiled |= set(re.findall(r"/\* (\S+\.swift) in Sources \*/", phase))

on_disk = {p.name for p in Path("macos/Guardian").rglob("*.swift")}
on_disk |= {p.name for p in Path("macos/GuardianTests").rglob("*.swift")}

missing = on_disk - compiled
if missing:
    problems.append(f"Swift files on disk but not compiled: {sorted(missing)}")
orphaned = compiled - on_disk
if orphaned:
    problems.append(f"compiled but missing from disk: {sorted(orphaned)}")

# 5. Every file reference should point at something that exists.
for name in set(re.findall(r"path = (\S+\.swift);", text)):
    if name not in on_disk:
        problems.append(f"file reference with no file on disk: {name}")

# 6. Every new file should also live in a group, or it is invisible in the navigator.
for name in sorted(on_disk):
    if f"/* {name} */," not in text:
        problems.append(f"not a child of any group (invisible in Xcode): {name}")

print(f"{len(declared)} objects, {len(phases)} sources phase(s), "
      f"{len(compiled)} sources compiled, {len(on_disk)} Swift files on disk")
for p in problems:
    print("  !", p)
print("\nPBXPROJ OK" if not problems else f"\n{len(problems)} PROBLEM(S)")
sys.exit(1 if problems else 0)
