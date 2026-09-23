# Lughus Agent Examples

Bibliothèque d'agents de production construits avec le micro-framework [Lughus](../README.md).

---

## 🔍 Data Ingestion & SQL Specialist Agent

L'agent [`data_ingestion_agent/`](data_ingestion_agent/) est un assistant SQL autonome hautement gouverné, conçu pour inspecter, profiler et requêter des bases de données relationnelles on-premise sans aucun risque de fuite de données ou de schéma (*Zero-Leak*).

### 🎯 Enjeux & Principes Lughus Illustrés

Dans un environnement d'entreprise, donner un accès direct à une base de données à un modèle de langage présente deux risques critiques :
1. **Les requêtes destructrices :** Injections SQL ou altérations accidentelles (`DROP`, `DELETE`, `UPDATE`, `ALTER`).
2. **La fuite d'informations (Data & Schema Leakage) :** Les erreurs SQLite/Postgres renvoyées brutes au LLM dévoilent les chemins physiques, schémas internes et données sensibles.

L'agent `data_ingestion_agent` applique les garanties du framework **Lughus** :
- **Ergonomie Pydantic-First :** Outils déclarés en Python typé avec docstrings Google, convertis automatiquement en schémas d'outils stricts.
- **Politique de Moindre Privilège (*Least Privilege*) :** Outils restreints à `ToolEffect.READ` et `ToolRisk.LOW`, connexion SQLite forcée en lecture seule via URI `mode=ro`.
- **Caviardage Sécurisé avec `SafeToolError` :** Toute exception interne ou tentative d'écriture est interceptée et remplacée par un code stable et un message générique sans trace de pile.

---

## 🏛️ Outils Métier Embarqués

Le registre d'outils ([`tools.py`](data_ingestion_agent/data_ingestion_agent/tools.py)) expose 4 fonctions strictement gouvernées :

| Outil | Description | Paramètres Pydantic | Effets & Risque |
| :--- | :--- | :--- | :--- |
| `list_tables` | Liste toutes les tables métier et leur volumétrie | Aucun | `ToolEffect.READ`, `ToolRisk.LOW` |
| `describe_table` | Inspecte le schéma d'une table (colonnes, types SQLite, clés) | `table_name: str` | `ToolEffect.READ`, `ToolRisk.LOW` |
| `sample_table` | Récupère un échantillon représentatif de lignes (paginé) | `table_name: str`, `limit: int = 5` | `ToolEffect.READ`, `ToolRisk.LOW` |
| `query_database` | Exécute une requête `SELECT` ou `WITH` read-only | `sql_query: str`, `max_rows: int = 100` | `ToolEffect.READ`, `ToolRisk.LOW` |

---

## 🚀 Démarrage Rapide

### 1. Installation

```bash
cd examples/data_ingestion_agent
uv venv && uv pip install -e ".[server]" pytest pytest-asyncio
```

### 2. Configuration

Renseignez vos variables d'environnement (compatible avec tous les fournisseurs supportés par LiteLLM : OpenAI, Anthropic, Mistral, Ollama, Gemini) :

```bash
export AGENT_MODEL="openai/gpt-4o"
export OPENAI_API_KEY="sk-..."
```

*(Un modèle `.env.example` est disponible dans le dossier de l'agent).*

### 3. Lancer l'Agent

```bash
python -m data_ingestion_agent
```

L'agent démarre par défaut sur `http://127.0.0.1:8081` :
- **Console Développeur Interactive :** `http://127.0.0.1:8081/ui`
- **Agent Card A2A :** `http://127.0.0.1:8081/.well-known/agent-card.json`
- **Endpoint RPC A2A :** `POST http://127.0.0.1:8081/`

---

## 🧪 Tests Offline (Zero Network / Zero API Key)

L'agent dispose d'une suite de tests complète et reproductible, exécutable hors-ligne sans clé API payante grâce à `MockLLM` :

```bash
cd examples/data_ingestion_agent
pytest tests/ -v
```
