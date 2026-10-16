"""Run four regression probes against an untouched archive of 9f6cc69, not this checkout."""
import ast
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

root=Path(__file__).resolve().parents[1]
selected={'test_relative_database_path_has_same_absolute_meaning_in_both_terminals',
          'test_duplicate_new_opportunity_reopens_existing_without_losing_work',
          'test_missing_sender_error_links_to_configuration_and_preserves_draft',
          'test_project_brief_includes_exact_recorded_acceptance_evidence'}
module=ast.parse((root/'tests/test_phase5_validation.py').read_text())
module.body=[node for node in module.body if not (isinstance(node,ast.Import) and any(alias.name=='runtime_status' for alias in node.names))]
for node in module.body:
    if isinstance(node,ast.ClassDef):
        node.body=[item for item in node.body if not isinstance(item,ast.FunctionDef) or item.name in selected]
with tempfile.TemporaryDirectory(prefix='agencyos-baseline-reproduction-') as temporary:
    archive=subprocess.check_output(['git','archive','9f6cc69'],cwd=root)
    with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
        contents.extractall(temporary,filter='data')
    (Path(temporary)/'tests/test_phase5_validation.py').write_text(ast.unparse(module))
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_phase5_validation.py','-v'],
                          cwd=temporary,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',AGENCYOS_AI_PROVIDER='',AGENCYOS_WEBSITE_FETCH='0'))
    # A failing runner is intentional here: these four probes must fail on the old commit.
    sys.exit(result.returncode)
