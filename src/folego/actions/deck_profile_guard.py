"""Opted-in, scoped recovery of known Steam Deck desktop profile failures."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import time
import uuid

from .. import paths
from ..adapters.deck_profiles import DESKTOP_URL, MIC_PROFILE, DeckProfiles
from ..orchestration.models import ActionPlan, ActionResult, Outcome, ResourceIdentity

ACTION = "accessibility.restore-desktop-profile"
KEYS = ("touchpad", "microphone")


class DeckProfileGuard:
    def __init__(self, *, profiles=None, store, coordinator, now=time.time):
        self.profiles = profiles or DeckProfiles()
        self.store, self.coordinator, self.now = store, coordinator, now
        self._fault_seen = {key: 0 for key in KEYS}
        self._healthy_seen = {key: 0 for key in KEYS}
        self._last_sample = None
        self._boot = None
        self._clock = None

    def annotate(self, report):
        observed = self.profiles.observe()
        report["desktop_profiles"] = observed
        for card in report.get("cards", []):
            row = observed.get(card.get("key"))
            if row is None:
                continue
            card["state"] = {"healthy": "observed", "fault": "degraded",
                             "unknown": "unknown"}.get(row.get("state"), "unknown")
            card["detail"] = row.get("detail", "perfil não comprovado")
        return observed

    def _pending(self, key, *, ignore=None):
        from .accessibility import unresolved
        scope = ('microphone', 'audio') if key == 'microphone' else ('touchpad', 'pointer', 'keyboard')
        return [item for item in unresolved(self.coordinator.journal, capabilities=scope) if item != ignore]

    @staticmethod
    def _game_blocker():
        """A missing/uncertain owner is not evidence that a game has ended."""
        state = paths._env_dir("XDG_STATE_HOME", Path.home() / ".local/state") / "retrofe/input-session"
        for name in ("steam-desktop-session.json", "kde-global-shortcut-guard.json"):
            path = state / name
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            except OSError:
                return "sessão RetroFE não comprovada"
            return "RetroFE ainda possui uma sessão de perfil/atalhos"
        known = {"RetroFE", "retroarch", "dolphin-emu", "pcsx2-qt", "flycast", "rpcs3",
                 "gamescope", "ES-DE", "emulationstatio", "quiver-launcher"}
        passive = {"systemd", "(sd-pam)", "ssh-agent", "portal-kde-veri", "kwin_wayland", "polkit-kde-auth"}
        try:
            for proc in Path("/proc").iterdir():
                if not proc.name.isdigit():
                    continue
                try:
                    if proc.stat().st_uid != os.getuid():
                        continue
                    name = (proc / "comm").read_text().strip()
                    if name in known:
                        return "jogo/frontend ativo; perfil de desktop preservado"
                    # Steam titles may not have a known process name. Inspect only
                    # this user's environment and never include its contents in logs.
                    try:
                        with (proc / "environ").open("rb") as source:
                            data = source.read(65537)
                    except PermissionError:
                        if name in passive:
                            continue
                        return "processo do usuário sem estado comprovado"
                    if len(data) > 65536:
                        return "ambiente de processo excede orçamento de leitura"
                    if any(part.startswith((b"SteamGameId=", b"SteamAppId=")) and
                           part.split(b"=", 1)[1] not in (b"", b"0", b"413080")
                           for part in data.split(b"\0")):
                        return "aplicativo Steam ativo; perfil de desktop preservado"
                except (FileNotFoundError, ProcessLookupError):
                    continue
        except OSError:
            return "processos de jogos não comprovados"
        return ""

    @staticmethod
    def _phasezero_audio_blocker(identity):
        marker = paths.xdg_config_home() / "phasezero/desktop-session.json"
        try:
            registered = marker.lstat()
            if (not stat.S_ISREG(registered.st_mode) or registered.st_uid != os.getuid()
                    or registered.st_size > 32768 or registered.st_mode & 0o022):
                return "registro do responsável de áudio não comprovado"
        except FileNotFoundError:
            return ""
        except OSError:
            return "responsável de áudio não comprovado"
        path = paths._env_dir("XDG_STATE_HOME", Path.home() / ".local/state") / "phasezero/desktop-session/preferences.json"
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_size > 32768 or info.st_mode & 0o022):
                raise ValueError("preferência externa sem identidade privada")
            value = json.loads(path.read_text())
            audio = value.get("audio", {})
            profiles = audio.get("profiles", {})
            if (type(value.get("schema_version")) is not int or value["schema_version"] != 1
                    or not isinstance(profiles, dict) or profiles.get(identity["card"]) != MIC_PROFILE):
                return "preferência do responsável externo diverge do microfone interno"
            defaults = audio.get("defaults", {})
            sources = audio.get("endpoints", {}).get("sources", {})
            if (not isinstance(defaults, dict) or defaults.get("source") != identity["default"]
                    or not isinstance(sources, dict)
                    or any(not isinstance(name, str) or
                           (identity["card"].removeprefix("alsa_card.") in name and "Headset" in name)
                           for name in sources)):
                return "preferência do responsável externo ainda contém entrada de fone/entrada padrão divergente"
            return ""
        except (OSError, ValueError, TypeError, AttributeError):
            return "preferência do responsável externo desconhecida"

    def _blocker(self, key, current, report):
        from .accessibility import fresh
        if not fresh(report):
            return 'amostra de sessão antiga ou incompleta'
        if key == 'microphone':
            return self._phasezero_audio_blocker(current['identity'])
        if report.get("backend") != "kwin" or report.get("errors"):
            return "sessão KDE/entrada não comprovada"
        from .accessibility import lease_blockers
        leases = lease_blockers(self.store.root)
        if leases:
            return "recurso em uso ou reparo por outro responsável: " + leases[0]
        if key == "touchpad":
            return self._game_blocker()
        return ''

    def manual_parameters(self, report):
        current = report.get('desktop_profiles', {}).get('microphone', {})
        if current.get('state') != 'fault' or not current.get('identity'):
            return None
        policy = self.store.read()
        baseline = policy['profile_baseline'].get('microphone')
        if baseline is None and current['identity'].get('recovery') == 'wireplumber-reprobe':
            baseline = {'card': current['identity']['card'], 'profile': MIC_PROFILE,
                        'default': 'mic-biglinux'}
        if baseline is None:
            return None
        return {'boot_id': report['boot_id'], 'before': current['identity'], 'baseline': baseline}

    def manual_repair(self, parent):
        state = self.coordinator.journal.state_of(parent.operation_id)
        if state is None or state.intent is None or state.intent.to_dict() != parent.to_dict():
            raise ValueError('intenção da recuperação manual não comprovada')
        plan = ActionPlan(ACTION, ResourceIdentity.entry('microphone'),
                          dict(parent.params['profile_recovery']), operation_id=parent.operation_id)
        return self._execute(plan, automatic=False)

    def manual_recovered(self, parent):
        """Observe a settled manual audio request without repeating its effect."""
        from .accessibility import fresh
        params = parent.params['profile_recovery']
        checked = self._native.collect()
        if (not fresh(checked) or checked['boot_id'] != params['boot_id']
                or not self._baseline_allowed('microphone', params, self.store.read(), automatic=False)):
            return False
        first = self.profiles.microphone()
        time.sleep(1)
        second = self.profiles.microphone()
        return (first == second and second.get('state') == 'healthy'
                and self._matches('microphone', second, params['baseline']) and fresh(checked))

    @staticmethod
    def _baseline_allowed(key, params, policy, *, automatic):
        baseline = policy['profile_baseline'].get(key)
        return baseline == params['baseline'] or (
            not automatic and baseline is None and key == 'microphone'
            and params['before'].get('recovery') == 'wireplumber-reprobe'
            and params['baseline'] == {'card': params['before']['card'],
                                       'profile': MIC_PROFILE, 'default': 'mic-biglinux'})

    def _baseline(self, key, current):
        identity = current.get("identity") or {}
        if key == "touchpad" and identity.get("url") == DESKTOP_URL:
            return {"type": identity["type"], "url": DESKTOP_URL,
                    "template_sha256": identity["template_sha256"]}
        if key == "microphone" and identity.get("active") == MIC_PROFILE:
            return {"card": identity["card"], "profile": MIC_PROFILE,
                    "default": "mic-biglinux" if identity.get("default") == "mic-biglinux" else "internal"}
        return None

    def _matches(self, key, before, baseline):
        identity = before.get("identity") or {}
        if key == "touchpad":
            return (identity.get("type") == baseline.get("type")
                    and identity.get("template_sha256") == baseline.get("template_sha256"))
        return (identity.get("card") == baseline.get("card") and baseline.get("profile") == MIC_PROFILE
                and ("mic-biglinux" if identity.get("default") == "mic-biglinux" else "internal") == baseline.get("default"))

    def budget_blocker(self, policy, key):
        now = self.now()
        if any(row['ts'] > now for row in policy['profile_attempts']):
            return 'relógio regressou; orçamento de reparo preservado'
        recent = [row for row in policy['profile_attempts'] if row['key'] == key
                  and 0 <= now - row['ts'] < 3600]
        if len(recent) >= 3:
            return 'três reparos em uma hora; conflito persistente'
        if recent and now - recent[-1]['ts'] < 120:
            return 'intervalo de 120 s entre reparos desta capacidade'
        return ''

    def tick(self, report):
        observed = report.get("desktop_profiles", {})
        if not observed:
            return None
        policy = self.store.read()
        report["profile_guard"] = {"enabled": policy["enabled"],
                                   "baseline": list(policy["profile_baseline"]),
                                   "circuit": dict(policy["profile_circuit"])}
        if not policy["enabled"]:
            return None
        from .accessibility import fresh
        if not fresh(report):
            self._fault_seen = {key: 0 for key in KEYS}
            self._healthy_seen = {key: 0 for key in KEYS}
            return None
        clock = report.get('clock', 'monotonic')
        if report['boot_id'] != self._boot or clock != self._clock:
            self._clock = clock
            self._boot, self._last_sample = report['boot_id'], None
            self._fault_seen = {key: 0 for key in KEYS}
            self._healthy_seen = {key: 0 for key in KEYS}
        mono = report['mono']
        if self._last_sample is not None:
            if mono <= self._last_sample:
                return None
            if mono - self._last_sample > 30:
                self._fault_seen = {key: 0 for key in KEYS}
                self._healthy_seen = {key: 0 for key in KEYS}
        self._last_sample = mono
        for key in KEYS:
            current = observed.get(key, {})
            if current.get("state") != "fault":
                self._fault_seen[key] = 0
                self._healthy_seen[key] = min(2, self._healthy_seen[key] + 1) if current.get("state") == "healthy" else 0
                if self._healthy_seen[key] >= 2 and key not in policy["profile_baseline"]:
                    baseline = self._baseline(key, current)
                    if baseline and not self._blocker(key, current, report):
                        with self.coordinator.lock(wait=.2):
                            latest = self.store.read()
                            if latest["enabled"] and key not in latest["profile_baseline"]:
                                latest["profile_baseline"][key] = baseline
                                self.store.save(latest)
                continue
            self._healthy_seen[key] = 0
            self._fault_seen[key] = min(2, self._fault_seen[key] + 1)
            if self._fault_seen[key] < 2:
                continue
            baseline = policy["profile_baseline"].get(key)
            if not baseline or policy["profile_circuit"].get(key):
                continue
            if current.get('identity', {}).get('recovery') and not policy['audio_reprobe_enabled']:
                continue
            if not self._matches(key, current, baseline) or self._blocker(key, current, report):
                continue
            if self._pending(key):
                continue
            budget = self.budget_blocker(policy, key)
            if budget:
                if budget == 'três reparos em uma hora; conflito persistente':
                    with self.coordinator.lock(wait=.2):
                        latest = self.store.read()
                        if self.budget_blocker(latest, key) == budget:
                            latest['profile_circuit'][key] = budget
                            self.store.save(latest)
                continue
            plan = ActionPlan(ACTION, ResourceIdentity.entry(key),
                              {"boot_id": report["boot_id"], "before": current["identity"],
                               "baseline": baseline},
                              notes=("Restaura somente o perfil saudável registrado; jogo ativo bloqueia.",))
            result = self.coordinator.run(plan, lambda _: self._execute(plan), wait=.2)
            self._fault_seen[key] = 0
            return {"ok": result.outcome == Outcome.OK,
                    "state": "repaired" if result.outcome == Outcome.OK else "waiting",
                    "outcome": str(result.outcome), "operation_id": result.operation_id,
                    "reason": result.reason, "profile": key}
        return None

    def _execute(self, plan, *, automatic=True):
        key = plan.target.key
        def result(outcome, reason):
            return ActionResult(ACTION, outcome, plan.operation_id, target_key=key, reason=reason)
        policy = self.store.read()
        if (automatic and not policy["enabled"]) or policy["profile_circuit"].get(key):
            return result(Outcome.REFUSED, "supervisão de perfis desligada ou suspensa")
        if (automatic and plan.params['before'].get('recovery')
                and not policy['audio_reprobe_enabled']):
            return result(Outcome.REFUSED, 'reenumeração automática de áudio desligada')
        if not self._baseline_allowed(key, plan.params, policy, automatic=automatic):
            return result(Outcome.REFUSED, "baseline de perfil mudou")
        if self._pending(key, ignore=plan.operation_id):
            return result(Outcome.REFUSED, "reparo anterior de perfil ainda incerto")
        # KWin and boot are revalidated immediately; no stale GUI report grants an effect.
        from .accessibility import fresh
        native = self._native
        checked = native.collect()
        if (not fresh(checked) or checked.get("boot_id") != plan.params["boot_id"]
                or (key == 'touchpad' and (checked.get('errors') or checked.get('backend') != 'kwin'))):
            return result(Outcome.REFUSED, "sessão/compositor mudou antes do reparo")
        before = self.profiles.steam() if key == "touchpad" else self.profiles.microphone()
        if (before.get("state") != "fault" or before.get("identity") != plan.params["before"]
                or not self._matches(key, before, plan.params["baseline"])):
            return result(Outcome.REFUSED, "perfil atual mudou; nenhuma ação aplicada")
        blocker = self._blocker(key, before, checked)
        if blocker:
            return result(Outcome.REFUSED, blocker)
        now = self.now()
        blocker = self.budget_blocker(policy, key)
        if blocker:
            return result(Outcome.REFUSED, blocker)
        attempts = [a for a in policy["profile_attempts"] if 0 <= now - a["ts"] < 3600]
        attempts.append({"key": key, "ts": now, "operation_id": plan.operation_id})
        policy["profile_attempts"] = attempts
        self.store.save(policy)  # The journal already contains the intent.
        try:
            self.profiles.restore(key, before)
            deadline = time.monotonic() + (8 if before['identity'].get('recovery') else 4)
            stable_since = None
            while time.monotonic() < deadline:
                after = self.profiles.steam() if key == "touchpad" else self.profiles.microphone()
                if after.get("state") == "healthy" and self._matches(key, after, plan.params["baseline"]):
                    stable_since = stable_since or time.monotonic()
                    if time.monotonic() - stable_since >= (2 if key == "touchpad" else 1):
                        return result(Outcome.OK, "perfil de desktop restaurado e confirmado; uso físico não testado")
                else:
                    stable_since = None
                time.sleep(.3)
        except (RuntimeError, OSError, ValueError, TimeoutError):
            pass
        policy = self.store.read()
        policy["profile_circuit"][key] = "efeito incerto; verificar antes de repetir"
        self.store.save(policy)
        return result(Outcome.UNKNOWN, "efeito incerto; nenhuma repetição automática")

    def bind_native(self, native):
        self._native = native

    def reconcile(self, operation_id, *, confirmed=False):
        if not confirmed:
            raise ValueError("reconciliação exige confirmação explícita")
        try:
            uuid.UUID(operation_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("ID de operação inválido") from exc
        with self.coordinator.lock(wait=.2):
            state = self.coordinator.journal.state_of(operation_id)
            if state is None or state.intent is None or state.intent.action != ACTION:
                raise ValueError("operação de perfil não encontrada")
            key = state.intent.target.key
            if key not in KEYS:
                raise ValueError("alvo de perfil desconhecido")
            if state.result is not None and state.result.outcome != Outcome.UNKNOWN:
                return state.result
            policy = self.store.read()
            baseline = policy["profile_baseline"].get(key)
            if baseline is None or baseline != state.intent.params["baseline"]:
                raise ValueError("baseline alterado; não é seguro reconciliar")
            current = self.profiles.steam() if key == "touchpad" else self.profiles.microphone()
            if current.get("state") != "healthy" or not self._matches(key, current, baseline):
                return ActionResult(ACTION, Outcome.UNKNOWN, operation_id, target_key=key,
                                    reason="perfil ainda não comprovado; nenhuma ação repetida")
            result = ActionResult(ACTION, Outcome.OK, operation_id, target_key=key,
                                  reason="perfil saudável observado; nenhuma ação reaplicada")
            self.coordinator.journal.append_result(result)
            return result

    def rearm(self, key, *, confirmed=False):
        if not confirmed or key not in KEYS:
            raise ValueError("perfil/confirmacão inválido")
        with self.coordinator.lock(wait=.2):
            policy = self.store.read()
            if self._pending(key):
                raise ValueError("operação de perfil pendente; reconcilie o ID antes")
            baseline = policy["profile_baseline"].get(key)
            current = self.profiles.steam() if key == "touchpad" else self.profiles.microphone()
            if (baseline is None or current.get("state") != "healthy"
                    or not self._matches(key, current, baseline)):
                raise ValueError("perfil saudável e baseline ainda não comprovados")
            policy["profile_circuit"].pop(key, None)
            policy["profile_attempts"] = [a for a in policy["profile_attempts"] if a["key"] != key]
            self.store.save(policy)
            return {"ok": True, "profile": key, "reason": "disjuntor rearmado após verificação"}

    def capture(self, key, *, confirmed=False):
        """Manual review of a healthy replacement baseline, without a device effect."""
        if not confirmed or key not in KEYS:
            raise ValueError("perfil/confirmação inválido")
        from .accessibility import fresh
        checked = self._native.collect()
        observe = self.profiles.steam if key == "touchpad" else self.profiles.microphone
        first = observe()
        time.sleep(.5)
        second = observe()
        if (not fresh(checked)
                or (key == 'touchpad' and (checked.get('backend') != 'kwin' or checked.get('errors')))
                or first.get("state") != "healthy" or second != first
                or self._blocker(key, second, checked)):
            raise ValueError("perfil saudável/sem dono não confirmado duas vezes")
        baseline = self._baseline(key, second)
        if baseline is None:
            raise ValueError("referência saudável desconhecida")
        with self.coordinator.lock(wait=.2):
            if self._pending(key):
                raise ValueError("operação de perfil pendente; reconcilie o ID antes")
            if observe() != second:
                raise ValueError("perfil mudou durante o registro")
            policy = self.store.read()
            policy["profile_baseline"][key] = baseline
            self.store.save(policy)
            return {"ok": True, "profile": key, "baseline": baseline,
                    "reason": "referência saudável registrada; disjuntor preservado"}
