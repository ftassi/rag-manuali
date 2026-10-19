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


def test_question_tail_preserves_the_requested_operation():
    from manuali_rag.structure import focus_question, target_terms

    assert focus_question('Ho inserito i dati: come li salvo?') == 'come li salvo?'
    assert target_terms('Quali orari imposto per gli slot?') == {'ora'}
    assert target_terms('Quale codice devo usare?') == {'codic'}


def test_specific_provider_context_wins_over_an_incidental_provider_mention():
    passages = passages_from_hits([hit(1,
        'GESTIONE ALFA:\n\n1. Creazione risorsa\n\nIl codice sarà usato anche dal provider.\n\n'
        '2. Dettaglio risorsa\n\nPremere Apri.\n\n'
        'GESTIONE BETA:\n\n1. Creazione Provider\n\n• Codice: inserire il codice della risorsa.\n\n'
        '2. Uscita\n\nPremere Chiudi.')])
    scores = rank_scores('Quale codice uso nel Provider?', passages, [0.6] * len(passages))
    best = passages[max(range(len(scores)), key=scores.__getitem__)]
    assert best.scope == 'GESTIONE BETA'


def test_parallel_fields_can_be_requested_by_their_contents_instead_of_labels():
    passages = passages_from_hits([hit(1,
        '1. Associazione risorse\n\n'
        'Nella sezione Destinatari, associare i reparti abilitati.\n\n'
        'Nella sezione Origini, associare i fornitori configurati.\n\n'
        '2. Uscita\n\nPremere Chiudi.')])
    selected = select_passages('Quali reparti e quali fornitori associo?', passages, [0.8, 0.85, 0.1])
    texts = ' '.join(passages[i].text for i in selected)
    assert 'reparti abilitati' in texts and 'fornitori configurati' in texts


def test_equally_supported_different_scopes_need_clarification():
    from manuali_rag.structure import ambiguous_choice

    passages = passages_from_hits([hit(1,
        'GESTIONE ALFA:\n\n1. Codici risorsa\n\n• Codice: uno\n\n'
        '2. Uscita\n\nPremere Chiudi.\n\n'
        'GESTIONE BETA:\n\n1. Codici risorsa\n\n• Codice: due\n\n'
        '2. Uscita\n\nPremere Chiudi.')])
    candidates = [p for p in passages if p.kind == 'field']
    assert ambiguous_choice('Quale codice inserisco?', candidates, [0.8, 0.81])
    assert not ambiguous_choice('In ALFA quale codice inserisco?', candidates, [0.8, 0.81])


def test_parallel_request_does_not_exclude_a_value_with_a_different_label():
    passages = passages_from_hits([hit(1,
        '1. Creazione Server\n\n• Servizi forniti: dati disponibili.\n\n'
        '2. Creazione Client\n\n'
        'Nella sezione Destinatari, associare i reparti abilitati.\n\n'
        'Nella sezione Origini, associare i fornitori configurati.')])
    question = 'Nel Client quali reparti associo e quali fornitori?'
    scores = rank_scores(question, passages, [0.6] * len(passages))
    selected = select_passages(question, passages, scores)
    text = ' '.join(passages[i].text for i in selected)
    assert 'reparti abilitati' in text and 'fornitori configurati' in text


def test_complementary_parameters_are_not_competing_contexts():
    from manuali_rag.structure import confident_context

    passages = passages_from_hits([hit(1,
        '1. Associazione risorse\n\n'
        'Nella sezione Destinatari, associare i reparti.\n\n'
        'Nella sezione Origini, associare i fornitori.\n\n'
        '2. Uscita\n\nPremere Chiudi.')])
    assert confident_context(passages, [0.60, 0.59, 0.2], 0)
    assert not confident_context(passages, [0.60, 0.59, 0.59], 0)


def test_shared_subject_does_not_add_an_unrequested_introduction():
    passages = passages_from_hits([hit(1,
        '1. Creazione Client\n\nSe il Client non esiste, procedere con la creazione.\n\n'
        'Nella sezione Destinatari, associare i reparti abilitati.\n\n'
        'Nella sezione Origini, associare i fornitori configurati.\n\n'
        '2. Uscita\n\nPremere Chiudi.')])
    selected = select_passages('Nel Client quali reparti e quali fornitori associo?',
                               passages, [0.75, 0.8, 0.85, 0.1])
    text = ' '.join(passages[i].text for i in selected)
    assert 'reparti abilitati' in text and 'fornitori configurati' in text
    assert 'non esiste' not in text


def test_initial_time_field_does_not_support_initial_login_credentials():
    from manuali_rag.structure import authentication_supported

    unrelated = passages_from_hits([hit(1,
        'GESTIONE ALFA:\n\n1. Pianificazione\n\n• Ora inizio: 08:00\n\n'
        '2. Uscita\n\nPremere Chiudi.')])
    assert not authentication_supported('Come faccio il login con password iniziale?', unrelated)
    assert authentication_supported('Come imposto l’ora inizio?', unrelated)
    relevant = passages_from_hits([hit(1,
        'GESTIONE ALFA:\n\n1. Autenticazione\n\nInserire nome utente e password.\n\n'
        '2. Uscita\n\nPremere Chiudi.')])
    assert authentication_supported('Come faccio il login?', relevant)


def test_creation_includes_fields_and_save_but_navigation_does_not():
    passages = passages_from_hits([hit(1,
        'SISTEMA ALFA:\n\n1. Creazione risorsa\n\n'
        'Aprire Risorse.\n\nPremere Nuova.\n\n'
        'Il codice viene generato dopo il salvataggio.\n\n'
        'Compilare:\n\n• Nome: inserire un nome.\n\n'
        '• Stato: mantenere Inattivo.\n\n'
        'Una volta completata la compilazione, cliccare su Salva.\n\n'
        '2. Eliminazione\n\nPremere Elimina.')])
    scores = [1.0] + [0.1] * (len(passages) - 1)
    selected = select_passages('Come creo una risorsa?', passages, scores)
    text = '\n'.join(passages[i].text for i in selected)
    assert 'Nome:' in text and 'Inattivo' in text and 'Salva' in text
    assert 'Elimina' not in text
    assert select_passages('Da dove creo una risorsa?', passages, scores) == [0]


def test_creation_does_not_take_fields_from_another_scope():
    passages = passages_from_hits([
        hit(1, 'SISTEMA ALFA:\n\n1. Creazione\n\nPremere Nuovo.\n\n'
            '2. Altro\n\nPremere Apri.'),
        hit(2, 'SISTEMA BETA:\n\n1. Creazione\n\nCompilare:\n\n'
            '• Nome: inserire il nome.\n\n2. Altro\n\nPremere Apri.'),
    ])
    selected = select_passages('Come creo?', passages, [1.0] + [0.1] * (len(passages) - 1))
    assert all(passages[i].scope == 'SISTEMA ALFA' for i in selected)
