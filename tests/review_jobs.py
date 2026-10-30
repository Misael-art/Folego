"""Presentation-only job seam. Real review/ID contracts have integration tests."""
class ReviewJobs:
    def review_and_run(self, action, target, *, title, text, confirm_fn, done, expected_scope=None):
        if confirm_fn(title, text):
            self.run(action, target, confirm=True, done=done)
        else:
            done({"ok": False, "outcome": "cancelamento", "reason": "Cancelado / cancelado: nenhum efeito solicitado"})
