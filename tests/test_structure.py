from manuali_rag.store import SearchHit
from manuali_rag.structure import (
    flat_heading,
    passages_from_hits,
    rank_scores,
    scope_tags,
    select_passages,
)


def hit(page, content, document='example', title='Nome modificabile'):
    return SearchHit(page, document, title, page, '', content, None, None, 0.5)


def test_titles_are_context_and_numbered_steps_stay_together():
    passages = passages_from_hits([hit(1,
        'GESTIONE ALFA:\n\n1. Creazione risorsa\n\n'
        'Per creare:\n\n1. Aprire il pannello.\n\n2. Premere Nuovo.\n\n'
        '2. Associazione risorsa\n\n1. Selezionare la risorsa.\n\n2. Premere Associa.')])
    assert len(passages) == 2
    assert all(p.kind == 'steps' for p in passages)
    assert 'Creazione risorsa' in passages[0].path
    assert 'Creazione risorsa' not in passages[0].text
    assert 'Aprire il pannello' in passages[0].text
    assert 'Premere Nuovo' in passages[0].text
    assert 'Associa' not in passages[0].text
    assert flat_heading('1. Aprire il pannello.') is None


def test_scope_and_list_continue_across_pages_without_crossing_document():
    passages = passages_from_hits([
        hit(1, 'GESTIONE ALFA:\n\n1. Parametri risorsa\n\nImpostare:\n\n• Inizio: oggi'),
        hit(2, '• Fine: domani\n\n2. Altra operazione\n\nPremere Conferma.'),
        hit(3, 'GESTIONE BETA:\n\n1. Provider\n\nPremere Crea.\n\n2. Accesso\n\nPremere Apri.'),
    ])
    field_list = next(p for p in passages if p.kind == 'fields')
    assert [h.page for h, _ in field_list.parts] == [1, 1, 2]
    assert field_list.scope == 'GESTIONE ALFA'
    assert 'Altra operazione' not in field_list.text
    assert scope_tags(passages) == {'alfa', 'beta'}


def test_renaming_the_file_does_not_change_section_context():
    content = '1. Creazione risorsa\n\nPremere Nuovo.\n\n2. Archiviazione\n\nPremere Archivia.'
    first = passages_from_hits([hit(1, content, title='Codice fornitore')])
    renamed = passages_from_hits([hit(1, content, title='Manuale esplicativo')])
    assert [p.contextual for p in first] == [p.contextual for p in renamed]


def test_nested_manuals_keep_the_existing_retrieval_path():
    assert not passages_from_hits([hit(1,
        '1.1 Accesso\n\nPremere Apri.\n\n1.2 Uscita\n\nPremere Chiudi.')])


def test_explicit_fields_choose_complete_parameter_list():
    passages = passages_from_hits([hit(1,
        '1. Impostazioni\n\nSezione parametri\n\nImpostare:\n\n'
        '• Azione: obbligatoria\n\n• Momento: iniziale\n\n• Profilo: standard\n\n'
        '2. Uscita\n\nPremere Chiudi.')])
    question = 'Come configuro azione, momento e profilo?'
    scores = rank_scores(question, passages, [0.6] * len(passages))
    best = passages[max(range(len(scores)), key=scores.__getitem__)]
    assert best.kind == 'fields'
    assert all(word in best.text for word in ['Azione', 'Momento', 'Profilo'])


def test_numeric_row_is_not_treated_as_a_heading():
    assert flat_heading('40') is None
    assert flat_heading('2.Creazione Provider') == 'Creazione Provider'


def test_requested_parameters_keep_values_from_both_pages():
    passages = passages_from_hits([
        hit(1, '1. Parametri\n\nStato limite modifica\n\n• Valore: A'),
        hit(2, 'Stato limite cancellazione\n\n• Valore: B\n\n2. Uscita\n\nPremere Chiudi.'),
    ])
    scores = [0.9 if p.kind == 'fields' else 0.6 for p in passages]
    selected = select_passages('Quali stati limite modifica e cancellazione?', passages, scores)
    texts = ' '.join(passages[i].text for i in selected)
    assert 'Valore: A' in texts and 'Valore: B' in texts


def test_repeated_opening_steps_belong_to_both_procedures():
    passages = passages_from_hits([hit(1,
        '1. Associazione e attivazione\n\nPer associare:\n\n'
        '1. Selezionare la risorsa.\n\n2. Aprire il menu.\n\n3. Premere Associa.\n\n'
        'Per attivare:\n\n1. Selezionare la risorsa.\n\n2. Aprire il menu.\n\n3. Premere Attiva.\n\n'
        '2. Uscita\n\nPremere Chiudi.')])
    activation = next(p for p in passages if 'Premere Attiva' in p.text)
    assert 'Selezionare la risorsa' in activation.text
    assert 'Aprire il menu' in activation.text
    assert 'Premere Associa' not in activation.text
