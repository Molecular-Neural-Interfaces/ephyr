# Reading Sources

You can import supported recordings into an Ephyr workspace from Python, without opening the desktop
app. The result is the same layout as **Add Config** / **Add Record** in the GUI
(see [Files Format](../files_format.md) for supported recordings and the folder structure).

Import is a generator: it yields progress as a fraction from `0` to `1` while writing samples, then
returns the Config and Record ids. Conversion is atomic: a cancelled or failed import leaves nothing
behind.

## Convert a single recording

```python
from pathlib import Path

from ephyr.converter.source_reader.source_reader_factory import SourceReaderFactory
from ephyr.core.fingerprint import fingerprint_of_ref
from ephyr.core.workspace import Workspace

parent = Path("/path/to/parent")
workspace = Workspace.create(parent, "study")          # or Workspace.open(parent / "study_ephyr")

recording = Path("/path/to/recording")                 # file or folder, depending on format
reader = SourceReaderFactory.get_reader(recording)
plan = reader.probe(scan=True)
fingerprint = fingerprint_of_ref(plan.ref)
name = plan.recording_name or plan.ref.name

generator = workspace.add_config(plan, name, name, plan.sources[0].source_id, fingerprint)
while True:
    try:
        progress = next(generator)
    except StopIteration as stop:
        location = stop.value
        break
    print(f"\rProgress: {progress * 100:.0f}%", end="", flush=True)

print("Created:", workspace.record_dir(location.config_id, location.record_id))
```

A recording whose channels already match a Config in the workspace is added with `workspace.add_record`
instead of `add_config`. `matching_configs` tells you which Configs it fits without blocking mismatches.

## Convert many recordings

The script below is the same as the root `test.py`: it opens or creates a workspace, probes each
candidate, skips duplicates by fingerprint, and adds a matching recording as a Record of the existing
Config.

Set `DIR_WITH_RECORDINGS` to scan the immediate children of one directory (both files and subfolders
are treated as candidates), or list the paths explicitly in `RECORDING_PATHS`.

```python
from pathlib import Path
from typing import List, Optional

from ephyr.converter.source_reader.source_reader_factory import SourceReaderFactory
from ephyr.core.fingerprint import fingerprint_of_ref
from ephyr.core.validation import matching_configs
from ephyr.core.workspace import Workspace, find_workspace_root

WORKSPACE_PARENT = Path("/data")
WORKSPACE_NAME = "study"

DIR_WITH_RECORDINGS: Optional[Path] = None
RECORDING_PATHS: List[Path] = [
    Path("/data/rec1.lfp"),
    Path("/data/openephys_session"),
]


def candidate_paths() -> List[Path]:
    if DIR_WITH_RECORDINGS is not None:
        return sorted(DIR_WITH_RECORDINGS.iterdir())
    return list(RECORDING_PATHS)


def open_or_create_workspace() -> Workspace:
    root = WORKSPACE_PARENT / Workspace.default_folder_name(WORKSPACE_NAME)
    if find_workspace_root(root) is not None:
        return Workspace.open(root)
    return Workspace.create(WORKSPACE_PARENT, WORKSPACE_NAME)


def run(generator):
    while True:
        try:
            progress = next(generator)
        except StopIteration as stop:
            print()
            return stop.value
        print(f"\r  progress: {progress * 100:.0f}%", end="", flush=True)


workspace = open_or_create_workspace()
converted, skipped, failed = [], [], []

for recording_path in candidate_paths():
    if find_workspace_root(recording_path) is not None:
        skipped.append(recording_path)
        continue
    try:
        reader = SourceReaderFactory.get_reader(recording_path)
        fingerprint = fingerprint_of_ref(reader.probe(scan=False).ref)
    except Exception as error:
        print(f"Unsupported format, skipping: {recording_path} ({error})")
        skipped.append(recording_path)
        continue

    duplicate = workspace.find_duplicate(fingerprint)
    if duplicate is not None:
        print(f"Already imported as {duplicate.config_id}/{duplicate.record_id}, skipping: {recording_path}")
        skipped.append(recording_path)
        continue

    try:
        plan = reader.probe(scan=True)
        name = plan.recording_name or plan.ref.name
        matches = matching_configs(workspace.configs(), plan)
        if matches:
            location = run(workspace.add_record(matches[0].config.config_id, plan, name, fingerprint))
        else:
            location = run(workspace.add_config(plan, name, name, plan.sources[0].source_id, fingerprint))
        converted.append(workspace.record_dir(location.config_id, location.record_id))
    except Exception as error:
        print(f"\n  failed: {error}")
        failed.append(recording_path)

print(f"Workspace: {workspace.root}")
print(f"Converted: {len(converted)}, skipped: {len(skipped)}, failed: {len(failed)}")
```

After conversion, open the workspace in the GUI or load a Record with `EphyrSessionManager`
(see [Using Labeled Data](labeled_data.md)).

## Notes

- `Workspace.default_folder_name("study")` is `study_ephyr`. `find_workspace_root` accepts the
  workspace folder, `workspace.ephyr`, or any path inside the workspace.
- `SourceReaderFactory.get_reader` raises when no reader recognises the path; catching it is what
  turns an unsupported file into a skip rather than a crash.
- `probe(scan=False)` is enough for the fingerprint and signature check. `probe(scan=True)` is needed
  before conversion when a reader takes its analog range from the signal peak.
- For WEEGIT sources point at the `.lfp` file itself; the matching `<name>.header.json` is picked up
  from the same folder.
- Run conversion scripts in the same Python environment where `ephyr` is installed
  (`pip install ephyr`).
