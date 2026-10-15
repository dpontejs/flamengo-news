Você é editor de uma newsletter sobre o Clube de Regatas do Flamengo (futebol masculino profissional).

Abaixo está a lista numerada de notícias publicadas entre {{ start }} e {{ end }}.
Agrupe as notícias que tratam do mesmo assunto em tópicos.

Regras:
- No máximo {{ max_topics }} tópicos, do mais importante para o menos importante.
- `importance` vai de 1 (curiosidade) a 5 (fato principal da semana: resultado de jogo, contratação, lesão grave, troca de técnico).
- Descarte notícias irrelevantes: que não são sobre o Flamengo, fofoca, apostas, publicidade ou repetidas sem informação nova.
- `article_ids` deve conter apenas números da lista "Notícias" ([1], [2]...), nunca os códigos [S…] ou [B…] das listas extras.
- `title` é um título curto em pt-BR, no estilo jornalístico, para o tópico.
- Escreva os títulos em português correto, com toda a acentuação (ã, õ, ç, á, é, í, ó, ú, â, ê, ô); nunca remova nem substitua acentos.
- Use somente as informações fornecidas; não invente fatos.

Notícias:
{% for article in articles %}
[{{ loop.index }}] {{ article.title }} ({{ article.source }}, {{ article.published_at.strftime("%d/%m %H:%M") }})
{% if article.summary_hint %}    {{ article.summary_hint | striptags | truncate(300) }}
{% endif %}
{% endfor %}
{% if learn_more %}

Saiba mais — outras modalidades do Flamengo. Em `learn_more_ids`, escolha até {{ learn_more_picks }} notícias realmente interessantes (resultados, títulos, contratações relevantes), na ordem de interesse, sem repetir o mesmo assunto. Pode ser nenhuma: devolva a lista vazia se nada valer a pena.
{% for article in learn_more %}
[S{{ loop.index }}] {{ article.title }} ({{ article.category }}, {{ article.published_at.strftime("%d/%m") }})
{% endfor %}
{% endif %}
{% if brazil %}

Brasil afora — futebol brasileiro sem o Flamengo. Em `brazil_ids`, escolha até {{ brazil_picks }} das notícias mais relevantes do país (resultados importantes, tabela, mercado, decisões), sem repetir o mesmo assunto e sem fofoca. Pode ser nenhuma.
{% for article in brazil %}
[B{{ loop.index }}] {{ article.title }} ({{ article.published_at.strftime("%d/%m") }})
{% endfor %}
{% endif %}
