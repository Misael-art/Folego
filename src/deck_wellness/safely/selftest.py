"""Manual safety-kernel proof: python -m deck_wellness.safely.selftest

Runs a full backup -> mutate -> restore roundtrip against a throwaway file in
the real XDG data dir and prints independently checkable evidence (shas,
paths, audit record). Touches nothing outside deck-wellness's own dirs.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

from .. import paths
from . import audit, backup


def main() -> int:
    data = paths.data_dir()
    scratch = data / "selftest"
    scratch.mkdir(parents=True, exist_ok=True)
    target = scratch / "probe.txt"
    original = f"deckwellness-probe-{time.time()}".encode()
    target.write_bytes(original)
    sha_original = hashlib.sha256(original).hexdigest()

    store = backup.BackupStore(paths.backup_dir())
    bid = store.create("selftest", [backup.BackupEntry(target=target, sha_after_expected=None)])
    print(f"[1] backup criado: {bid}")
    print(f"    sha256 original: {sha_original}")

    target.write_bytes(b"CONTAMINADO")
    print("[2] alvo corrompido de proposito (CONTAMINADO)")

    results = store.restore(bid)
    restored_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    ok = results[0].ok and restored_sha == sha_original
    print(f"[3] restore ok={results[0].ok} sha restaurado: {restored_sha}")

    log = audit.AuditLog()
    log.append(kind="apply", action_id="selftest", outcome="ok" if ok else "verify_fail",
               targets=[str(target)], backup_id=bid, risk="low", actor="selftest")
    print(f"[4] registro de auditoria em: {log.path}")
    print(f"    ultimo: {json.dumps(log.tail(1)[0], ensure_ascii=False)[:120]}...")

    print(f"\nmanifest: {json.dumps(store.read_manifest(bid)['entries'][0], indent=2)}")
    print("RESULTADO:", "PASS — backup/restore byte-idêntico" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
