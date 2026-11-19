from promotores_kpi_dashboard.chat_queries import asks_for_unsupported_period, classify_question, find_focus, find_named_entity, find_person, find_sku, is_route_question


def test_chat_intents():
    assert classify_question("¿Qué clientes no compraron Pure Gold?") == "non_buyers"
    assert classify_question("¿Cuántos clientes activé hoy?") == "last_activations"
    assert classify_question("¿Cuántos compraron?") == "buyers"
    assert classify_question("Hola") is None


def test_direct_question_without_filters():
    question = "CUANTOS CLIENTES DE PURE GOLD TIENE NICASTRO LUCAS"
    assert classify_question(question) == "buyers"
    assert find_named_entity(question, ["NICASTRO LUCAS", "SIRI MARTIN"]) == "NICASTRO LUCAS"
    assert find_sku(question, ["Todos", "PURE GOLD TODOS", "STELLA ARTOIS TODOS"]) == "PURE GOLD TODOS"


def test_previous_month_is_not_mislabeled_as_current():
    assert asks_for_unsupported_period("¿Cuántos compraron en septiembre?", 10)
    assert not asks_for_unsupported_period("¿Cuántos compraron en octubre?", 10)


def test_follow_up_entities():
    assert find_person("¿Cuántos clientes tiene Enzo?", ["VILLAGRA ENZO", "NICASTRO LUCAS"]) == "VILLAGRA ENZO"
    assert is_route_question("¿De qué ruta es Enzo?")
    assert not is_route_question("De la ruta de LUJU")
    assert find_named_entity("De la ruta de LUJU", ["LUJU", "MAVI"]) == "LUJU"
    assert find_focus("¿Y de Value?") == "Value"
