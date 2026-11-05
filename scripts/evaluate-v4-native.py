"""QA nativo: consulta processos/candidatos e cria atalho somente em fixture.

Não abre aplicativos encontrados, não toca na inicialização real do Windows
e não ativa política ou memória pessoal. Resultado contém apenas contagens.
"""
from pathlib import Path
import json
import os
import sys
import uuid


def main():
    root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
    from therion.autonomy.apps import process_paths,discover_applications
    from therion.autonomy.windows import StartupShortcut,SingleInstance,session_unlocked
    fixture=root/'tmp'/'v4-tests'/('native-'+uuid.uuid4().hex)
    fixture.mkdir(parents=True)
    paths=process_paths()
    own=os.path.normcase(os.path.realpath(sys.executable))
    assert own in paths,'Não confirmei o processo Python pelo caminho completo.'
    candidates=discover_applications()
    assert len({os.path.normcase(row['path']) for row in candidates})==len(candidates)
    shortcut=StartupShortcut(startup=fixture)
    shortcut.set_enabled(True)
    assert shortcut.path.is_file()
    shortcut.set_enabled(True)  # Repetição explícita de configuração idempotente.
    shortcut.set_enabled(False)
    assert not shortcut.path.exists()
    shortcut.path.write_bytes(b'foreign shortcut fixture')
    rejected=False
    try:shortcut.set_enabled(False)
    except ValueError:rejected=True
    assert rejected and shortcut.path.read_bytes()==b'foreign shortcut fixture'
    shortcut.path.unlink()  # Somente o arquivo fictício criado acima.
    one=SingleInstance('native-fixture-'+fixture.name);two=SingleInstance('native-fixture-'+fixture.name)
    try:assert one.acquired and not two.acquired
    finally:one.close();two.close()
    result=dict(process_path_verified=True,discovered_candidates=len(candidates),
        discovery_unique=True,fixture_shortcut_created_and_removed=True,
        foreign_shortcut_preserved=True,single_instance_verified=True,
        session_unlocked=session_unlocked(),real_startup_modified=False,
        applications_launched=0,personal_policies_activated=0)
    (fixture/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));print('Relatório:',fixture/'report.json')
    return 0


if __name__=='__main__':sys.exit(main())
