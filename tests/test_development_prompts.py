import hashlib

from folego.core.development_prompts import CONTEXT, PROMPTS, text


def test_design_mockups_prompt_preserves_the_complete_user_text():
    prompt = next(p for p in PROMPTS if p.key == 'design-mockups')
    assert prompt.title == 'Design e mockups para aprovação'
    # SHA of the supplied UTF-8 attachment: no generic preamble or truncation.
    assert hashlib.sha256(text(prompt.key).encode('utf-8')).hexdigest() == (
        '679b411c224337653971fe662e62a854f704a703203310f393c59bed06b0e8a9')


def test_existing_prompts_keep_their_context_and_catalog_ids_are_unique():
    assert len(PROMPTS) == len({p.key for p in PROMPTS}) == 12
    for prompt in PROMPTS:
        if prompt.key != 'design-mockups':
            assert text(prompt.key) == CONTEXT + '\n\n' + prompt.body
