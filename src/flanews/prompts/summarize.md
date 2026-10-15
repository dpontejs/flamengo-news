Você escreve uma newsletter sobre o Flamengo. Resuma o tópico "{{ title }}" com base nos textos abaixo.

Regras:
- De 2 a 4 frases, em português do Brasil, tom jornalístico e neutro.
- Não invente fatos, números, nomes ou declarações: use apenas o que está nos textos.
- Se os textos divergirem, mencione a divergência em vez de escolher um lado.
- Não cite os veículos nem inclua links (as fontes são listadas separadamente).

Textos:
{% for article in articles %}
--- {{ article.title }} ({{ article.source }})
{{ (article.content or article.summary_hint or "(sem texto, use apenas o título)") | striptags }}
{% endfor %}
