# 🔍 Data Ingestion & SQL Specialist Agent

> **Description :** Ingestion SQL, inspection de schéma et requêtage analytique Zero-Leak.  
> **Framework :** [Lughus v0.22.0](../../README.md)  
> **Protocole d'exposition :** [A2A (Agent-to-Agent)](https://google.github.io/A2A/) sur le port `8081` avec Developer Console `/ui`.

---

## 🎯 Mission & Enjeux Métier

Dans un système décisionnel autonome, donner un accès direct et non-surveillé à une base de données d'entreprise à un modèle de langage présente deux risques critiques :
1. **Les requêtes destructrices :** Injections SQL accidentelles ou malveillantes (`DROP`, `DELETE`, `UPDATE`).
2. **La fuite d'informations (Data & Schema Leakage) :** Lorsqu'une requête échoue, la trace d'erreur brute du moteur (chemins physiques sur disque, structures internes, extraits de données) est renvoyée au LLM, l'exposant aux attaques par prompt injection indirecte.

Cet agent résout ces deux problématiques en appliquant les principes fondamentaux de **Lughus v0.22** :
- **Ergonomie Pydantic-First :** Déclaration de fonctions Python typées avec docstrings Google, converties automatiquement en schémas d'outils stricts.
- **Politique de Moindre Privilège (Least Privilege) :** Outils restreints à `ToolEffect.READ` et `ToolRisk.LOW`.
- **Caviardage Sécurisé avec `SafeToolError` :** Toute exception interne de SQLite est interceptée et remplacée par un code stable et un message générique sûr.

---

## 🏛️ Outils Métier Embarqués

Le registre d'outils ([`data_ingestion_agent/tools.py`](data_ingestion_agent/tools.py)) expose 4 fonctions hautement gouvernées :

| Outil | Description | Paramètres Pydantic | Effets & Risque |
| :--- | :--- | :--- | :--- |
| `list_tables` | Liste toutes les tables métier et leur volumétrie | Aucun | `ToolEffect.READ`, `ToolRisk.LOW` |
| `describe_table` | Inspecte le schéma d'une table (colonnes, types SQLite, clés) | `table_name: str` | `ToolEffect.READ`, `ToolRisk.LOW` |
| `sample_table` | Récupère un échantillon représentatif de lignes (paginé) | `table_name: str`, `limit: int = 5` | `ToolEffect.READ`, `ToolRisk.LOW` |
| `query_database` | Exécute une requête `SELECT` ou `WITH` read-only | `sql_query: str`, `max_rows: int = 100` | `ToolEffect.READ`, `ToolRisk.LOW` |

### 🛡️ Anatomie d'un Outil Sécurisé avec `SafeToolError`

```python
from lughus import ConcurrencyMode, SafeToolError, ToolEffect, ToolRegistry, ToolRisk

registry = ToolRegistry()

@registry.tool(
    name="query_database",
    risk=ToolRisk.LOW,
    effects=frozenset([ToolEffect.READ]),
    concurrency=ConcurrencyMode.PARALLEL_SAFE,
    idempotent=True,
)
def query_database(sql_query: str, max_rows: int = 100) -> str:
    """Execute a read-only SQL query against the database to extract analytical metrics.

    Args:
        sql_query: The SELECT or WITH query to execute. Mutative statements are strictly rejected.
        max_rows: Maximum rows to return (default: 100, max: 500).
    """
    clean_query = sql_query.strip()
    if not (clean_query.upper().startswith("SELECT") or clean_query.upper().startswith("WITH")):
        raise SafeToolError("READ_ONLY_VIOLATION", "Only read-only SELECT or WITH statements are allowed.")

    try:
        # Exécution en URI SQLite read-only
        ...
    except sqlite3.Error as exc:
        # Masquage de la trace de pile interne
        raise SafeToolError(
            "SQL_SYNTAX_OR_EXECUTION_ERROR",
            "The SQL query could not be executed. Please verify column names, aliases, and SQL syntax.",
        ) from exc
```

---

## 📊 Jeu de Données de Démonstration

Au premier lancement, [`database.py`](data_ingestion_agent/database.py) initialise automatiquement une base locale SQLite réaliste (`data/logistics_bi.db`) :
- `warehouses` : 5 entrepôts logistiques régionaux (Paris, Lyon, Marseille, Lille, Bordeaux).
- `customers` : 30 entreprises réparties par tiers (Enterprise, Mid-Market, SMB).
- `orders` : 200 commandes échelonnées sur 9 mois en 2026.
- `fulfillment_delays` : Suivi des délais de livraison réels vs prévus, avec une **anomalie volumétrique injectée au T3 (Q3)** sur le hub de Paris (surcharge opérationnelle).

---

## 🚀 Démarrage & Exécution

### 1. Variables d'Environnement

Configurez votre modèle LLM (compatible tout provider LiteLLM : OpenAI, Anthropic, Mistral, Ollama) :

```bash
export OPENAI_API_KEY="sk-..."
export AGENT_MODEL="openai/gpt-4o"
```

### 2. Initialiser la Base Démo (Optionnel)

Pour initialiser ou vérifier la base locale SQLite sans démarrer le serveur :

```bash
python -m data_ingestion_agent --seed
```

### 3. Lancer le Serveur A2A

```bash
python -m data_ingestion_agent
```

L'agent démarre sur `http://127.0.0.1:8081` :
- **Console Web de Débogage :** `http://127.0.0.1:8081/ui`
- **Agent Card A2A :** `http://127.0.0.1:8081/.well-known/agent-card.json`
- **Endpoint RPC A2A :** `POST http://127.0.0.1:8081/`

---

## 🧪 Tests Offline (Zero Network / Zero API Key)

Cet agent dispose d'une suite de tests complète exécutable sans connexion internet ni clé API payante grâce à `MockLLM` :

```bash
pytest tests/ -v
```
