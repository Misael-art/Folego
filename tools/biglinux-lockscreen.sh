#!/usr/bin/bash
# Manual BigLinux repair. The Fôlego application never invokes this tool.
set -euo pipefail
export PATH=/usr/bin LC_ALL=C
umask 077

fail() { echo "$*" >&2; exit 1; }
hash_is() {
    [[ -f $1 && ! -L $1 ]] && [[ $(sha256sum < "$1") == "$2  -" ]]
}
absent() { [[ ! -e $1 && ! -L $1 ]]; }
owned_mask() {
    [[ -L $mask && -L $marker && $(readlink "$marker") == /dev/null &&
       $(stat -c '%d:%i' "$mask") == "$(stat -c '%d:%i' "$marker")" ]]
}

wrapper_hash=59f669ed8981e0b520ecd5fe9f61b414fb9a6cac5718ded9d38c75137b318fc0
native_hash=e6d1d10d6d6348429328e641bec01e8d2805bd8963cd8fa92f391a205881a00f
bin=/usr/lib/kscreenlocker_greet
original=${bin}_orig
backup=/usr/lib/.folego-kscreenlocker_greet-6.8.2-1.wrapper
hooks=/etc/pacman.d/hooks
marker=/etc/pacman.d/.folego-kscreenlocker_greet.disabled
mask=$hooks/kscreenlocker_greet.hook

mode=${1:---check}
case "$mode" in --check|--apply|--undo|--release-hook) ;; *) fail 'Use --check, --apply, --undo ou --release-hook.' ;; esac
if [[ $mode != --check ]]; then
    (( EUID == 0 )) || fail 'A alteração de /usr/lib requer administrador no terminal do host.'
    if [[ $# == 1 ]]; then
        exec paclock --run --fail-ok -- /usr/bin/bash "$0" "$mode" --locked
    fi
    [[ $# == 2 && $2 == --locked ]] || fail 'Argumentos inválidos.'
fi

for dir in /usr/lib /etc/pacman.d "$hooks"; do
    if [[ $dir == "$hooks" ]] && absent "$dir"; then continue; fi
    [[ -d $dir && ! -L $dir && $(stat -c '%u:%g:%a' "$dir") == 0:0:755 ]] || fail "Diretório inesperado: $dir"
done
if [[ $mode == --release-hook ]]; then
    # After a distribution update, return control without writing an older executable.
    owned_mask || fail 'A máscara ativa não pertence a este reparo.'
    unlink "$mask"
    unlink "$marker"
    echo 'Hook da distribuição liberado para a próxima transação.'
    exit 0
fi

# Exact host package and bytes. A future vendor revision needs a fresh review.
[[ $(pacman -Q kscreenlocker) == 'kscreenlocker 6.8.2-1' ]] || fail 'Versão KDE diferente.'
[[ $(pacman-conf HookDir) == '/etc/pacman.d/hooks/' ]] || fail 'Diretório de hooks diferente.'
hash_is /usr/share/libalpm/hooks/kscreenlocker_greet.hook 13a93a58579f24caa8f11aeabb717aca453a2f8a8e4a09b9966c821e4220af67 || fail 'Hook diferente.'
hash_is /usr/share/libalpm/scripts/kscreenlocker_greet 95bdf89851156d635e299ddf12f9a78655142f7704920f9037ac21c8c3c8a84c || fail 'Instalador BigLinux diferente.'
hash_is "$original" "$native_hash" && [[ $(stat -c '%u:%g:%a' "$original") == 0:0:755 ]] || fail 'Executável original desconhecido.'
hash_is "$bin" "$wrapper_hash" || hash_is "$bin" "$native_hash" || fail 'Entrada do bloqueador desconhecida.'
[[ $(stat -c '%u:%g:%a' "$bin") == 0:0:755 ]] || fail 'Permissões do bloqueador diferentes.'
absent "$backup" || { hash_is "$backup" "$wrapper_hash" && [[ $(stat -c '%u:%g:%a' "$backup") == 0:0:755 ]]; } || fail 'Backup diferente.'
absent "$marker" || [[ -L $marker && $(readlink "$marker") == /dev/null ]] || fail 'Marcador diferente.'
absent "$mask" || owned_mask || fail 'Já existe uma política local para este hook.'

if hash_is "$bin" "$native_hash"; then state=nativo; else state=wrapper; fi
if owned_mask; then policy=mascarado; else policy=original; fi
echo "Bloqueador $state, hook $policy."
if [[ $mode == --check ]]; then exit 0; fi

replace_entry() (
    local source=$1 expected=$2
    local staging
    staging=$(mktemp -d /usr/lib/.folego-lockscreen-XXXXXXXX)
    # Only this invocation owns these two paths.
    trap 'rm -f -- "$staging/entry"; rmdir -- "$staging"' EXIT
    cp --preserve=all --reflink=auto -- "$source" "$staging/entry"
    hash_is "$staging/entry" "$expected" || fail 'Cópia divergente.'
    mv -Tf -- "$staging/entry" "$bin"
)

if [[ $mode == --apply ]]; then
    if [[ $state == wrapper ]] && absent "$backup"; then ln -T -- "$bin" "$backup"; fi
    hash_is "$backup" "$wrapper_hash" || fail 'Origem já nativa sem recibo deste reparo.'
    if absent "$hooks"; then install -d -m 755 "$hooks"; fi
    if absent "$marker"; then ln -sT /dev/null "$marker"; fi
    if absent "$mask"; then ln -PT -- "$marker" "$mask"; fi
    owned_mask || fail 'Máscara de hook sem identidade confirmada.'
    if [[ $state == wrapper ]]; then replace_entry "$original" "$native_hash"; fi
    hash_is "$bin" "$native_hash" || fail 'Verificação final falhou.'
    echo 'Bloqueador KDE restaurado. A próxima chamada já usa o executável do pacote.'
else
    if absent "$backup"; then
        [[ $state == wrapper ]] && absent "$marker" && absent "$mask" || fail 'Sem backup próprio para desfazer.'
        exit 0
    fi
    if [[ $state == nativo ]]; then replace_entry "$backup" "$wrapper_hash"; fi
    if owned_mask; then unlink "$mask"; fi
    if ! absent "$marker"; then unlink "$marker"; fi
    unlink "$backup"
    echo 'Entrada BigLinux e política anterior restauradas.'
fi
