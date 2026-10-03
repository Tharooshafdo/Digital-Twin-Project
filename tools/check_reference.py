"""Verify archived files and record exact reused-source differences."""
import argparse,hashlib,json,zipfile,difflib
from pathlib import Path
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--archive',default=str(Path.home()/'Downloads/Transmission_Line_Twin_Reference_Project_v2.zip'));args=parser.parse_args()
archive=Path(args.archive);reference=root/'reference/transmission_line_twin_reference'
report={'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'archive_files':[],'reused_sources':[]}
with zipfile.ZipFile(archive) as zipped:
    for entry in zipped.infolist():
        if entry.is_dir():continue
        relative=Path(entry.filename).relative_to('transmission_line_twin_reference')
        identical=zipped.read(entry)==(reference/relative).read_bytes()
        report['archive_files'].append({'path':str(relative),'byte_identical':identical})
        assert identical,relative
for path in (reference/'src/tl_twin').glob('*.py'):
    reused=root/'src/tl_twin'/path.name
    same=path.read_bytes()==reused.read_bytes()
    entry={'path':path.name,'byte_identical':same,'original_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'application_sha256':hashlib.sha256(reused.read_bytes()).hexdigest()}
    if not same:entry['diff']=''.join(difflib.unified_diff(path.read_text().splitlines(keepends=True),reused.read_text().splitlines(keepends=True),fromfile='reference/'+path.name,tofile='application/'+path.name))
    report['reused_sources'].append(entry)
(root/'docs/evidence/reference-comparison.json').write_text(json.dumps(report,indent=2))
print(json.dumps({'archive_files_verified':len(report['archive_files']),'reused_sources':len(report['reused_sources']),'changed_sources':[v['path'] for v in report['reused_sources'] if not v['byte_identical']]}))
