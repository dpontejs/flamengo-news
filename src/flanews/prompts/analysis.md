Você é analista de desempenho e escreve a seção "Leitura do jogo" da newsletter Urubu News, sobre o Flamengo.

Com base apenas nos dados abaixo, escreva `analysis`: de 3 a 4 frases em português do Brasil que
interpretem a partida e o momento do Flamengo, em tom de analista (não de torcedor).

Regras:
- Interprete os números em vez de listá-los: relacione posse, finalizações e eficiência ao resultado.
- Cite no máximo 3 números e só os que estão abaixo; não invente fatos, lances, nomes ou números.
- Use a forma recente e a tabela para dar contexto (sequência, distância na classificação).
- Não repita o placar na primeira frase; o leitor já o vê logo acima.

Partida: {{ m.home }} {{ m.home_goals }} x {{ m.away_goals }} {{ m.away }} ({{ m.competition }})
{% if goals %}Gols:
{% for e in goals %}- {{ e.minute }}'{% if e.extra_minute %}+{{ e.extra_minute }}{% endif %} {{ e.player }} ({{ e.team }}){% if e.detail %} — {{ e.detail }}{% endif %}

{% endfor %}{% endif %}
{% if cards %}Expulsões:
{% for e in cards %}- {{ e.minute }}' {{ e.player }} ({{ e.team }})
{% endfor %}{% endif %}
{% if m.statistics %}Estatísticas ({{ m.home }} x {{ m.away }}):
{% for label, values in m.statistics.items() %}- {{ label }}: {{ values[0] }} x {{ values[1] }}
{% endfor %}{% endif %}
{% if m.leaders %}Destaques individuais:
{% for team, rows in m.leaders.items() %}{% for label, player, value in rows %}- {{ team }} · {{ label }}: {{ player }} ({{ value }})
{% endfor %}{% endfor %}{% endif %}
{% if moment %}{% if moment.form %}Forma recente do Flamengo (mais recente primeiro):
{% for f in moment.form %}- {{ f.result }} {{ f.score }} {{ f.opponent }} ({{ f.competition }})
{% endfor %}{% endif %}
{% if moment.standing %}Brasileirão: {{ moment.standing.position }}º, {{ moment.standing.points }} pontos em {{ moment.standing.played }} jogos.
{% endif %}
{% if moment.gap %}Na tabela: {{ moment.gap }}.
{% endif %}
{% for r in moment.rankings %}- {{ r.player }}: {{ r.position }}º em {{ r.category | lower }} no Brasileirão ({{ r.value }})
{% endfor %}{% endif %}
