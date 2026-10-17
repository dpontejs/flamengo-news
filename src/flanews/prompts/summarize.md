Você escreve uma newsletter sobre o Flamengo. Resuma cada tópico abaixo com base nos textos dele.
Se houver itens curtos ([S…] e [B…]), escreva também uma única frase para cada um em `briefs`, com `item_id` igual ao código do item (ex.: "S1", "B2").

Regras:
- Um resumo por tópico, identificado pelo número do tópico (`topic_id`, ex.: 1 para [T1]).
- De 2 a 4 frases por resumo, em português do Brasil, tom jornalístico e neutro.
- Não invente fatos, números, nomes ou declarações: use apenas o que está nos textos do próprio tópico.
- Se os textos divergirem, mencione a divergência em vez de escolher um lado.
- Não cite os veículos nem inclua links (as fontes são listadas separadamente).

{% for topic in topics %}
=== [T{{ loop.index }}] {{ topic.title }}
{% for article in topic.articles %}
--- {{ article.title }} ({{ article.source }})
{{ (article.content or article.summary_hint or "(sem texto, use apenas o título)") | striptags | truncate(4000) }}
{% endfor %}

{% endfor %}
{% if learn_more or brazil %}

Itens curtos (uma frase cada, em português do Brasil, sem inventar):
{% for article in learn_more %}
=== [S{{ loop.index }}] {{ article.title }} ({{ article.category }})
{{ (article.content or article.summary_hint or "(sem texto, use apenas o título)") | striptags | truncate(1500) }}
{% endfor %}
{% for article in brazil %}
=== [B{{ loop.index }}] {{ article.title }}
{{ (article.content or article.summary_hint or "(sem texto, use apenas o título)") | striptags | truncate(1500) }}
{% endfor %}
{% endif %}
