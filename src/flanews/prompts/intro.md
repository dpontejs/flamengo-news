Você escreve a abertura da newsletter "Urubu News", sobre o Flamengo,{% if label %} ({{ label }}){% endif %}.

Regras:
- `headline`: uma manchete curta (até 80 caracteres) com o fato mais importante da edição.
- `intro`: exatamente 2 frases em português do Brasil resumindo a edição, em tom jornalístico e neutro.
- Use apenas as informações abaixo; não invente fatos.

{% if next_match %}Esta é a edição de pré-jogo: a manchete e a abertura apresentam o próximo jogo.
Próximo jogo: Flamengo x {{ next_match.opponent }} ({{ next_match.competition }}, {{ next_match.date.strftime("%d/%m às %H:%M") }}{% if next_match.venue %}, {{ next_match.venue }}{% endif %})
{% endif %}
{% if last_match %}Última partida: {{ last_match.home }} {{ last_match.home_goals }} x {{ last_match.away_goals }} {{ last_match.away }} ({{ last_match.competition }}, {{ last_match.date.strftime("%d/%m") }})
{% endif %}
{% if topics %}Tópicos da edição, do mais ao menos importante:
{% for topic in topics %}- {{ topic.title }}: {{ topic.summary }}
{% endfor %}{% endif %}
