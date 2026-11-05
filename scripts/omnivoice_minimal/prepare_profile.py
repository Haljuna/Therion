"""Exporta somente o perfil escolhido; não modifica o banco do VoiceStudio."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


def export_profile(data_root, profile_id, destination):
    data_root, destination = Path(data_root).resolve(), Path(destination).resolve()
    database = data_root / 'omnivoice.db'
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute('SELECT * FROM voice_profiles WHERE id=?', (profile_id,)).fetchone()
        if row is None:
            raise ValueError('Perfil salvo não encontrado')
        row = dict(row)
    finally:
        connection.close()
    voices = (data_root / 'voices').resolve()
    relative = row.get('locked_audio_path') if row.get('is_locked') else row.get('ref_audio_path')
    reference = (voices / (relative or '')).resolve()
    if not reference.is_relative_to(voices) or not reference.is_file():
        raise ValueError('Referência inválida ou fora da pasta de vozes')
    if not (row.get('ref_text') or '').strip():
        raise ValueError('O perfil precisa ter a transcrição da referência salva')
    if destination.exists():
        raise FileExistsError('Exportação já existe; não será sobrescrita')
    destination.parent.mkdir(parents=True, exist_ok=True)
    (destination.parent / '.gitignore').write_text('*\n', encoding='utf-8')
    manifest = {key: row.get(key) for key in ('id', 'name', 'ref_text', 'instruct', 'seed')}
    manifest.update(reference_path=str(reference),
                    reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                    source_database_sha256=before)
    destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    if hashlib.sha256(database.read_bytes()).hexdigest() != before:
        raise RuntimeError('Banco mudou durante a leitura; revisar exportação antes de usar')
    return {'id': row['id'], 'name': row['name'], 'database_unchanged': True,
            'reference_sha256': manifest['reference_sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--profile-id', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(export_profile(args.data_root, args.profile_id, args.output)))
