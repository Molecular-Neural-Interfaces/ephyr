# Reading Sources

You can convert supported recordings into `*_ephyr` experiment folders from Python with `EphyrIO`,
without opening the desktop app. The result is the same layout as **File → Open** in the GUI
(see [Files Format](../files_format.md) for supported sources and folder structure).

`convert_from_source_to_ephyr` is a generator: it yields progress percentages while writing
`header.json` and the `data/` memmaps. By default the output folder is created next to the source as
`{stem}_ephyr`; pass `out_dir` to override that path.

## Convert a single recording

```python
from pathlib import Path

from ephyr.converter.ephyr_io import EphyrIO

source_path = Path("/path/to/recording")  # file or folder, depending on format
out_ephyr_folder = source_path.parent / f"{source_path.stem}_ephyr"

for progress in EphyrIO.convert_from_source_to_ephyr(source_path):
    print(f"\rProgress: {progress}%", end="", flush=True)

print("Created:", out_ephyr_folder)
```

## Convert many recordings

The script below converts a batch of recordings the same way the GUI does: it resolves the output
folder with `EphyrIO.ephyr_dir_of_experiment` (which returns `(already_an_experiment, out_dir)`),
skips paths that already contain a valid experiment, probes the format with
`SourceReaderFactory.get_reader` (so unsupported paths are skipped instead of raising), and removes a
partially written folder if a conversion fails midway.

Set `DIR_WITH_EXPERIMENTS` to scan the immediate children of one directory (both files and
subfolders are treated as candidates), or list the paths explicitly in `EXPERIMENT_PATHS`.

```python
import shutil
from pathlib import Path
from typing import List, Optional

from ephyr.converter.ephyr_io import EphyrIO
from ephyr.converter.source_reader.source_reader_factory import SourceReaderFactory

# Either scan every child of one directory...
DIR_WITH_EXPERIMENTS: Optional[Path] = None
# ...or list the recordings yourself (a file for WEEGIT / ABF / EDF / NWB, a folder for Open Ephys / Intan).
EXPERIMENT_PATHS: List[Path] = [
    Path("/data/rec1.lfp"),
    Path("/data/openephys_session"),
]


def candidate_paths() -> List[Path]:
    if DIR_WITH_EXPERIMENTS is not None:
        return sorted(DIR_WITH_EXPERIMENTS.iterdir())
    return list(EXPERIMENT_PATHS)


converted: List[Path] = []
skipped: List[Path] = []
failed: List[Path] = []

for experiment_path in candidate_paths():
    is_already_experiment, out_dir = EphyrIO.ephyr_dir_of_experiment(experiment_path)

    if is_already_experiment or EphyrIO.is_valid_ephyr_folder(out_dir):
        print(f"Already converted, skipping: {experiment_path}")
        skipped.append(experiment_path)
        continue

    try:
        SourceReaderFactory.get_reader(experiment_path)
    except Exception as error:
        print(f"Unsupported format, skipping: {experiment_path} ({error})")
        skipped.append(experiment_path)
        continue

    print(f"Converting {experiment_path} -> {out_dir}")
    try:
        for progress in EphyrIO.convert_from_source_to_ephyr(experiment_path, out_dir):
            print(f"\r  progress: {progress}%", end="", flush=True)
        print()
        converted.append(out_dir)
    except Exception as error:
        print(f"\n  failed: {error}")
        # header.json is written before the data, so a half-converted folder
        # would look valid on the next run.
        shutil.rmtree(out_dir, ignore_errors=True)
        failed.append(experiment_path)

print(f"\nConverted: {len(converted)}, skipped: {len(skipped)}, failed: {len(failed)}")
for path in failed:
    print("  failed:", path)
```

After conversion, open the resulting folder in the GUI or load it with `EphyrSessionManager`
(see [Using Labeled Data](labeled_data.md)).

## Notes

- `EphyrIO.ephyr_dir_of_experiment` uses the path stem, so `/data/rec1.lfp` becomes
  `/data/rec1_ephyr` and `/data/openephys_session` becomes `/data/openephys_session_ephyr`.
- `SourceReaderFactory.get_reader` raises `ValueError: Unsupported experiment format` when no reader
  recognises the path; catching it is what turns an unsupported file into a skip rather than a crash.
- For WEEGIT sources point at the `.lfp` file itself; the matching `<name>.header.json` is picked up
  from the same folder.
- Run conversion scripts in the same Python environment where `ephyr` is installed
  (`pip install ephyr`).
