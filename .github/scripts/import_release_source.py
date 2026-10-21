"""Import public sources from a verified program release; never import user data."""
import hashlib,json,shutil,sys,zipfile
from pathlib import Path,PurePosixPath
folder=Path(sys.argv[1])
manifest=json.loads((folder/"program-update.json").read_text())
filename=manifest["file"]
if Path(filename).name!=filename or not filename.endswith("-Windows.zip"):raise ValueError("Invalid asset")
packed=folder/filename
with packed.open("rb") as stream:
    if hashlib.file_digest(stream,"sha256").hexdigest()!=manifest["sha256"]:raise ValueError("Checksum mismatch")
if packed.stat().st_size!=manifest["bytes"]:raise ValueError("Package size mismatch")
allowed={"app","addon","MediaScraper","build-source","licenses"}
entries=[]
with zipfile.ZipFile(packed) as archive:
    total=0
    for item in archive.infolist():
        parts=PurePosixPath(item.filename).parts
        if len(parts)<2 or any(p in ("..",".") or ":" in p for p in parts) or "\\" in item.filename:raise ValueError("Unsafe archive path")
        relative=parts[1:]
        if relative[0] not in allowed and relative!=("release.json",):continue
        if any(p in ("userdata","profile",".auth","source_sessions","__pycache__","node_modules") for p in relative):raise ValueError("Private directory in source archive")
        if item.filename.endswith((".pyc",".pyo")) or item.is_dir():continue
        total+=item.file_size
        if total>100*1024**2:raise ValueError("Source archive too large")
        target=Path("release_tools" if relative[0]=="build-source" else relative[0]).joinpath(*relative[1:])
        entries.append((item,target))
    for item,target in entries:
        target.parent.mkdir(parents=True,exist_ok=True)
        with archive.open(item) as source,target.open("wb") as output:shutil.copyfileobj(source,output)
if Path("addon/LICENSE.txt").exists():shutil.copy2("addon/LICENSE.txt","LICENSE")
if not Path(".gitignore").exists():Path(".gitignore").write_text("/userdata/\n/app/profile/\n**/.auth/\n**/source_sessions/\n__pycache__/\n*.pyc\n*.sqlite3*\n*.zip\n*.exe\nnode_modules/\n/runtime/\n/data/\n/distribution/\n.env\n")
Path("SOURCE-VERSION.json").write_text(json.dumps({"version":manifest["version"],"program_sha256":manifest["sha256"]},indent=2)+"\n")
print("Imported",len(entries),"public source files for",manifest["version"])
