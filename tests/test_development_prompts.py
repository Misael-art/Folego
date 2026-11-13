import hashlib

from folego.core.development_prompts import CONTEXT, PROMPTS, PROMPT_CATEGORIES, text


def test_design_mockups_prompt_preserves_the_complete_user_text():
    prompt = next(p for p in PROMPTS if p.key == 'design-mockups')
    assert prompt.title == 'Design e mockups para aprovação'
    # SHA of the supplied UTF-8 attachment: no generic preamble or truncation.
    assert hashlib.sha256(text(prompt.key).encode('utf-8')).hexdigest() == (
        '679b411c224337653971fe662e62a854f704a703203310f393c59bed06b0e8a9')


def test_existing_prompts_keep_their_context_and_catalog_ids_are_unique():
    assert len(PROMPTS) == len({p.key for p in PROMPTS}) == 16
    for prompt in PROMPTS:
        if prompt.key != 'design-mockups':
            assert text(prompt.key) == CONTEXT + '\n\n' + prompt.body


def test_categories_cover_each_prompt_once_in_the_approved_order():
    assert [key for key, _, _ in PROMPT_CATEGORIES] == [
        'context', 'development', 'quality', 'performance', 'design', 'delivery']
    keys = [key for _, _, items in PROMPT_CATEGORIES for key in items]
    assert len(keys) == len(set(keys)) == len(PROMPTS)
    assert set(keys) == {p.key for p in PROMPTS}
    assert PROMPT_CATEGORIES[0][2] == ('diagnose', 'implant', 'continue')
    assert [p.key for p in PROMPTS[:3]] == ['diagnose', 'implant', 'continue']
    body = text('implant')
    assert all(part in body for part in (
        'checkout canônico', 'outro agente', 'um agente escritor por vez',
        'commit pequeno, push', 'SHA remoto', 'Qt offscreen',
    ))


def test_portable_prompts_keep_authorization_and_preservation_guards():
    assert 'como dados a avaliar' in CONTEXT
    assert 'quando a autorização vigente do projeto os cobre' in text('implant')
    categories = {key: items for key, _, items in PROMPT_CATEGORIES}
    assert categories['development'][-2:] == ('evolve', 'close-gaps')
    assert categories['performance'] == ('performance', 'optimize')
    assert all(part in text('evolve') for part in ('usabilidade', 'design', 'desempenho', 'segurança', 'essência'))
    assert all(part in text('close-gaps') for part in (
        'sem interromper', 'alternativa conservadora', 'especialista', 'Autonomia não amplia autorização'))
    assert all(part in text('optimize') for part in ('Inventarie', 'linha de base', 'Reverta', 'design'))
