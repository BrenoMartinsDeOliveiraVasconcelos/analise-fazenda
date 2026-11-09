# analise-fazenda
Trabalho de faculdade para analise de dados de uma fazenda

# Executando o script

Para executar o script, primeiro instale Python e execute na pasta do projeto o seguinte comando:

`python main.py`

NOTA: Troque o `python` pela localização do executável caso tenha instalado com um nome diferente.

Abaixo segue o trabalho que precisou ser realizado.

# Squad 5 — A carga que não podia misturar

## A dor

Leite de vaca, de búfala e de cabra são produtos diferentes, com preço, destino
e rótulo diferentes. **Não podem ser misturados**: se forem, a carga perde a
identidade e é descartada inteira.

Leite orgânico misturado com convencional não é descarte, mas perde a
certificação e passa a ser pago como convencional — e o produtor orgânico perde
justamente o prêmio que paga o custo extra de manter a certificação.

A cooperativa separa as rotas por causa disso: cada caminhão roda uma rota de
uma classe só. Mas o compartimento é único, e a operação real não é limpa — o
motorista cobre a rota do colega que faltou, um tanque é incluído fora da rota,
a segunda viagem do dia junta o que sobrou.

Quando o laticínio recusa a carga, já se perdeu o rastro de qual foi e de quem
estava dentro. **Nunca ninguém somou quanto isso custou no ano.**

## O que a solução deve resolver

Levantar no histórico todas as cargas em que houve mistura proibida, dizer
quais fazendas estavam dentro de cada uma, e quanto dinheiro se perdeu —
separando as duas violações, porque elas custam muito diferente.

## Onde estão os dados

| O que você precisa | Arquivo | Colunas |
|---|---|---|
| A espécie e a certificação de cada fazenda | `fazendas.csv` | `especie`, `certificacao` |
| O que não pode misturar, e o efeito | `regras_compatibilidade.csv` | todas |
| Quais fazendas entraram em cada carga | `coletas.csv` | `carga_id`, `fazenda_id`, `volume`, `unidade` |
| Data, caminhão e viagem de cada carga | `cargas.csv` | `data`, `caminhao_id`, `viagem_no_dia`, `volume_total_litros` |
| O preço do litro e o prêmio do orgânico | `parametros.csv` | `preco_base_litro`, `premio_organico_litro` |

**As duas violações custam diferente:**

| Violação | O que se perde | Quanto |
|---|---|---|
| Espécies diferentes | a carga **inteira** | litros × R$ 2,45 |
| Orgânico com convencional | só o **prêmio** do orgânico | litros orgânicos × R$ 0,35 |

## O que o algoritmo deve responder

### Nível 1

- Cada fazenda é de qual espécie e qual certificação?
- Quantas fazendas existem de cada combinação, e em quais tanques elas estão?

### Nível 2 — **este é o exigido**

- Cada carga levou leite de quais fazendas?
- Alguma carga juntou espécies diferentes, ou juntou orgânico com convencional?
- Quais cargas foram, em que data, com qual caminhão, e com quais fazendas
  dentro?
- Quantos litros ficaram comprometidos e quanto isso custou — aplicando a regra
  certa a cada tipo de violação?

### Nível 3 — bônus, não vale nota

- Quais caminhões repetem o erro?
- Em que mês, em qual viagem do dia, e com que frequência?
- A segunda viagem erra mais que a primeira?

## O painel

O usuário escolhe **um mês**. O painel devolve:

- as cargas irregulares daquele mês;
- o tipo de violação de cada uma;
- as fazendas envolvidas;
- os litros comprometidos e o prejuízo em reais;
- o ranking de caminhões reincidentes.

## Os dois casos com resposta

Use-os na verificação:

| Mês | Cargas irregulares | Prejuízo |
|---|---|---|
| Março | **20** | **R$ 328.944,00** |
| Abril | **8** | **R$ 154.966,35** |

> **Na entrega, o professor vai escolher outro mês.** A solução tem de
> responder para qualquer entrada válida. Isso é requisito, não surpresa.

## Cuidados

- **Tratar as duas violações com o mesmo custo é o erro mais caro deste
  projeto.** A diferença é de sete vezes por litro: você acerta a contagem de
  cargas e erra todos os valores.
- Uma carga é **caminhão + dia + viagem**. Ignorar a `viagem_no_dia` funde duas
  cargas legítimas numa violação que não existe.
- Parte das coletas está em **quilo**, não em litro.
- Há cargas sem silo de destino em `cargas.csv` — são linhas de lixo, e o
  dicionário explica como identificá-las.
- Há coletas com data impossível e coletas apontando para fazenda inexistente.
  Se elas entrarem na conta, aparecem violações que nunca aconteceram.
