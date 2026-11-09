import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
import os

import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader

MESES = {3: "Março", 4: "Abril", 5: "Maio", 6: "Junho"}
ROTULO_VIOLACAO = {
    "descarte_total": "Espécies diferentes (descarte total)",
    "perda_premio": "Orgânico com convencional (perda de prêmio)",
}


@dataclass
class Config:
    """Caminhos e constantes do projeto."""
    pasta_dados: Path
    template: Path = Path(__file__).with_name("template.html")
    saida: Path = Path(__file__).with_name("dashboard.html")
    # Densidade do leite (kg/L). Calibrada nos dados: com 1,032 a soma das
    # coletas converte exatamente para o volume_total_litros de cada carga.
    densidade_kg_l: float = 1.032

class DataLoader:
    """Lê os CSVs (separador ';', com BOM) e os parâmetros de preço."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _csv(self, nome: str) -> pd.DataFrame:
        return pd.read_csv(self.cfg.pasta_dados / nome, sep=";", encoding="utf-8-sig")

    def carregar(self) -> dict:
        parametros = self._csv("parametros.csv").set_index("parametro")["valor"]
        return {
            "fazendas": self._csv("fazendas.csv"),
            "cargas": self._csv("cargas.csv"),
            "coletas": self._csv("coletas.csv"),
            "regras": self._csv("regras_compatibilidade.csv"),
            "preco_base": float(parametros["preco_base_litro"]),
            "premio_organico": float(parametros["premio_organico_litro"]),
        }


class DataCleaner:
    """Remove registros inválidos e converte tudo para litros.
    Guarda quantos registros foram descartados e por quê (transparência)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.descartes: list[dict] = []

    def _registrar(self, motivo: str, qtd: int) -> None:
        self.descartes.append({"motivo": motivo, "qtd": int(qtd)})

    def limpar(self, cargas, coletas, fazendas):
        # Cargas sem silo de destino são linhas de lixo.
        valida = cargas["silo_id"].notna()
        self._registrar("Cargas sem silo de destino (linhas de lixo)", (~valida).sum())
        cargas = cargas[valida].copy()

        # Coletas apontando para fazenda inexistente.
        valida = coletas["fazenda_id"].isin(fazendas["fazenda_id"])
        self._registrar("Coletas de fazenda inexistente", (~valida).sum())
        coletas = coletas[valida]

        # Coletas com data impossível (31/04, 2026-02-30, 0000-00-00...).
        datas = pd.to_datetime(coletas["data"], format="%Y-%m-%d", errors="coerce")
        self._registrar("Coletas com data impossível", datas.isna().sum())
        coletas = coletas[datas.notna()]

        # Coletas que não pertencem a nenhuma carga válida.
        valida = coletas["carga_id"].isin(cargas["carga_id"])
        self._registrar("Coletas sem carga válida", (~valida).sum())
        coletas = coletas[valida].copy()

        # Quilos -> litros.
        eh_litro = coletas["unidade"] == "L"
        coletas["litros"] = np.where(eh_litro, coletas["volume"],
                                     coletas["volume"] / self.cfg.densidade_kg_l)
        self._registrar("Coletas em quilo convertidas para litro (mantidas)", (~eh_litro).sum())

        cargas["mes"] = pd.to_datetime(cargas["data"]).dt.month
        return cargas, coletas

class CompatibilityRules:
    """Intepreta apartir do arquivo regras_compatibilidade.csv regras de compayibilidade."""

    PRIORIDADE = ["descarte_total", "perda_premio"]

    def __init__(self, regras: pd.DataFrame):
        self.regras = regras.to_dict("records")

    def violacao(self, valores_por_atributo: dict) -> str | None:
        """Recebe {'especie': {...}, 'certificacao': {...}} de uma carga e
        devolve a consequência mais grave encontrada (ou None)."""
        achadas = {
            r["consequencia"] for r in self.regras
            if {r["valor_a"], r["valor_b"]} <= valores_por_atributo.get(r["atributo"], set())
        }
        return next((c for c in self.PRIORIDADE if c in achadas), None)


class CostCalculator:
    """Aplica a regra de custo certa a cada tipo de violação."""

    def __init__(self, preco_base: float, premio_organico: float):
        self.preco_base = preco_base
        self.premio = premio_organico

    def calcular(self, violacao: str, litros_carga: float, litros_organicos: float):
        """Devolve (litros comprometidos, prejuízo em R$)."""
        if violacao == "descarte_total":      # carga inteira vai fora
            return litros_carga, litros_carga * self.preco_base
        return litros_organicos, litros_organicos * self.premio  # só o prêmio


class IrregularityDetector:
    """Cruza coletas x fazendas e classifica cada carga."""

    def __init__(self, rules: CompatibilityRules, custo: CostCalculator):
        self.rules, self.custo = rules, custo

    def analisar(self, cargas, coletas, fazendas) -> pd.DataFrame:
        itens = coletas.merge(fazendas[["fazenda_id", "especie", "certificacao"]], on="fazenda_id")
        linhas = []
        for carga_id, grupo in itens.groupby("carga_id"):
            violacao = self.rules.violacao({
                "especie": set(grupo["especie"]),
                "certificacao": set(grupo["certificacao"]),
            })
            litros_org = grupo.loc[grupo["certificacao"] == "organico", "litros"].sum()
            linhas.append((carga_id, violacao, litros_org))
        res = pd.DataFrame(linhas, columns=["carga_id", "violacao", "litros_org"])

        res = cargas.merge(res, on="carga_id", how="left")
        res["litros_carga"] = res["volume_total_litros"].astype(float)
        comprometidos, prejuizos = [], []
        for r in res.itertuples():
            if r.violacao:
                litros, valor = self.custo.calcular(r.violacao, r.litros_carga, r.litros_org)
            else:
                litros, valor = 0.0, 0.0
            comprometidos.append(round(litros, 1))
            prejuizos.append(round(valor, 2))
        res["litros_comprometidos"], res["prejuizo"] = comprometidos, prejuizos
        return res


class PayloadBuilder:
    """Transforma os resultados em um dicionário JSON para o JavaScript."""

    def __init__(self, fazendas, cargas, coletas, descartes, cfg: Config):
        self.fazendas, self.cargas, self.coletas = fazendas, cargas, coletas
        self.descartes, self.cfg = descartes, cfg
        self.indice = {f: i for i, f in enumerate(fazendas["fazenda_id"])}

    def _nivel1(self):
        fazendas = [
            {"id": r.fazenda_id, "nome": r.nome_fazenda, "esp": r.especie,
             "cert": r.certificacao, "tanque": r.tanque_id}
            for r in self.fazendas.itertuples()
        ]
        combos = []
        for (esp, cert), g in self.fazendas.groupby(["especie", "certificacao"]):
            tanques = g["tanque_id"].value_counts().sort_index()
            combos.append({"esp": esp, "cert": cert, "qtd": len(g),
                           "tanques": [[t, int(n)] for t, n in tanques.items()]})
        return fazendas, combos

    def _cargas(self):
        composicao = {
            cid: [[self.indice[r.fazenda_id], round(r.litros, 1)] for r in g.itertuples()]
            for cid, g in self.coletas.groupby("carga_id")
        }
        return [
            {"id": r.carga_id, "data": r.data, "mes": int(r.mes), "cam": r.caminhao_id,
             "viagem": int(r.viagem_no_dia), "litros": r.litros_carga,
             "viol": r.violacao if isinstance(r.violacao, str) else None,
             "comp": r.litros_comprometidos, "prej": r.prejuizo,
             "fz": composicao.get(r.carga_id, [])}
            for r in self.cargas.itertuples()
        ]

    @staticmethod
    def _resumo(df: pd.DataFrame) -> dict:
        """KPIs, ranking de caminhões e taxa de erro por viagem de um recorte."""
        err = df[df["violacao"].notna()]
        caminhoes = (
            df.groupby("caminhao_id").agg(cargas=("carga_id", "size"))
            .join(err.groupby("caminhao_id").agg(
                erros=("carga_id", "size"), prejuizo=("prejuizo", "sum")))
            .fillna(0).reset_index()
        )
        caminhoes = caminhoes[caminhoes["erros"] > 0].copy()
        caminhoes["taxa"] = caminhoes["erros"] / caminhoes["cargas"] * 100
        caminhoes = caminhoes.sort_values(["erros", "prejuizo"], ascending=False)

        viagens = df.groupby("viagem_no_dia").size().rename("cargas").to_frame().join(
            err.groupby("viagem_no_dia").size().rename("erros")).fillna(0).reset_index()
        viagens["taxa"] = viagens["erros"] / viagens["cargas"] * 100

        return {
            "kpi": {"cargas": len(df), "irregulares": len(err),
                    "esp": int((err["violacao"] == "descarte_total").sum()),
                    "premio": int((err["violacao"] == "perda_premio").sum()),
                    "litros": float(err["litros_comprometidos"].sum()),
                    "prejuizo": float(err["prejuizo"].sum()),
                    "prej_esp": float(err.loc[err["violacao"] == "descarte_total", "prejuizo"].sum()),
                    "prej_premio": float(err.loc[err["violacao"] == "perda_premio", "prejuizo"].sum())},
            "caminhoes": [{"cam": r.caminhao_id, "cargas": int(r.cargas), "erros": int(r.erros),
                           "taxa": round(r.taxa, 1), "prejuizo": round(r.prejuizo, 2)}
                          for r in caminhoes.itertuples()],
            "viagens": [{"viagem": int(r.viagem_no_dia), "cargas": int(r.cargas),
                         "erros": int(r.erros), "taxa": round(r.taxa, 1)}
                        for r in viagens.itertuples()],
        }

    def construir(self) -> dict:
        fazendas, combos = self._nivel1()
        visoes = {"total": self._resumo(self.cargas)}
        for mes in MESES:
            visoes[str(mes)] = self._resumo(self.cargas[self.cargas["mes"] == mes])
        return {
            "meses": [{"num": n, "nome": nome} for n, nome in MESES.items()],
            "rotulos": ROTULO_VIOLACAO,
            "limpeza": self.descartes,
            "fazendas": fazendas, "combos": combos,
            "cargas": self._cargas(), "visoes": visoes,
        }

class DashboardRenderer:
    """Injeta o JSON no template Jinja2 e grava o HTML final."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def renderizar(self, payload: dict) -> Path:
        env = Environment(loader=FileSystemLoader(self.cfg.template.parent))
        # "</" é escapado para o JSON não fechar a tag <script> por acidente.
        dados = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
        html = env.get_template(self.cfg.template.name).render(dados_json=dados)
        self.cfg.saida.write_text(html, encoding="utf-8")
        return self.cfg.saida



def main() -> None:
    dados = Path(__file__).parent

    cfg = Config(pasta_dados=dados)

    dados = DataLoader(cfg).carregar()
    limpador = DataCleaner(cfg)
    cargas, coletas = limpador.limpar(dados["cargas"], dados["coletas"], dados["fazendas"])

    detector = IrregularityDetector(
        CompatibilityRules(dados["regras"]),
        CostCalculator(dados["preco_base"], dados["premio_organico"]))
    resultado = detector.analisar(cargas, coletas, dados["fazendas"])

    payload = PayloadBuilder(dados["fazendas"], resultado, coletas,
                             limpador.descartes, cfg).construir()
    saida = DashboardRenderer(cfg).renderizar(payload)

    print(f"Dashboard gerado em: {saida}")


if __name__ == "__main__":
    main()
