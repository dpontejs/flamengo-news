Você escreve uma newsletter sobre o Flamengo. Resuma cada tópico abaixo com base nos textos dele.

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
{{ (article.content or article.summary_hint or "(sem texto, use apenas o título)") | striptags }}
{% endfor %}

{% endfor %}
