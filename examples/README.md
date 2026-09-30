# 🏛️ Catalogue & Guide d'Ingénierie des Agents Lughus

> **Bibliothèque de référence d'agents autonomes de production construits sur [Lughus v0.22](../../README.md).**  
> Chaque sous-répertoire constitue un micro-projet autonome, auto-suffisant, fortement typé, exposé via le protocole standardisé **A2A (Agent-to-Agent)** et testable hors-ligne sans clé API payante.

---

## 🎯 Philosophie & Principes Directeurs

Les agents de ce répertoire ne sont pas de simples scripts de démonstration ou des wrappers d'APIs : ce sont des **références architecturales concrètes** illustrant les principes fondamentaux de sécurité, de gouvernance et de robustesse promus par le micro-framework `lughus` :

```
             ┌────────────────────────────────────────────────────────┐
             │               Interface & Transport A2A                │
             │     A2A JSON-RPC / SSE  │  Developer Console (/ui)     │
             └───────────────────────────┬────────────────────────────┘
                                         │
                                         ▼
             ┌────────────────────────────────────────────────────────┐
             │            Gateway & Orchestration de Session          │
             │        BaseGateway  │  Workspace (Request-Scoped)      │
             └───────────────────────────┬────────────────────────────┘
                                         │
                                         ▼
             ┌────────────────────────────────────────────────────────┐
             │            Boucle Agent & Outils Gouvernés             │
             │    agent_loop  │  ToolRegistry (Typed Pydantic)        │
             └─────────────┬───────────────────────────┬──────────────┘
                           │                           │
                           ▼                           ▼
             ┌───────────────────────────┐ ┌──────────────────────────┐
             │   Gouvernance & Sécurité  │ │   Isolation & Exécution  │
             │ BudgetLedger │ SafeToolError │ OCI Sandbox │ Read-Only DB │
             └───────────────────────────┘ └──────────────────────────┘
```

1. **Ergonomie Pydantic-First & Typage Strict :** Les outils sont des fonctions Python typées avec docstrings Google, converties automatiquement en schémas JSON Schema stricts contrôlés par Pydantic. Aucune manipulation arbitraire de dictionnaires `dict[str, Any]` n'est admise dans la logique métier.
2. **Moindre Privilège (*Least Privilege*) & Déclaration d'Effets :** Chaque outil déclare explicitement ses effets (`ToolEffect.READ`, `ToolEffect.WRITE`, etc.), son niveau de risque (`ToolRisk.LOW`, `ToolRisk.HIGH`), ses scopes de sécurité, son idempotence et son mode de concurrence (`PARALLEL_SAFE`, `SERIAL_PER_TOOL`).
3. **Sécurité *Fail-Closed* & Caviardage des Erreurs :** 
   - Toute exécution de code dynamique est confinée par défaut dans un conteneur OCI isolé, sans accès réseau, utilisateur non-root et racine en lecture seule. Aucun repli silencieux vers l'hôte n'est toléré en cas d'indisponibilité du moteur.
   - Les exceptions internes (traces SQL, erreurs système, chemins d'accès) sont interceptées et caviardées via `SafeToolError` : seuls des messages et codes d'erreur sûrs et stables sont exposés au modèle.
4. **Gouvernance des Ressources & FinOps :** Les appels au modèle, l'exécution des outils, le temps d'exécution et le volume de tokens sont strictement bornés par `BudgetLimit`, `BudgetLedger` et `BudgetedLLM`.
5. **Contexte Biaisé & Données Non-Fiables :** Toute pièce jointe ou donnée externe injectée dans le contexte est formellement balisée avec `TrustLevel.EXTERNAL` et bornée en taille pour immuniser l'agent contre le prompt injection indirect.
6. **Reproductibilité & Tests Hors-Ligne (Zero-Network / Zero-Cost) :** Chaque agent dispose d'une suite de tests reproductibles exécutables sans connexion Internet ni consommation d'APIs payantes grâce au moteur `lughus.testing.MockLLM`.

---

## 📚 Catalogue des Agents Publiés

| Agent | Épisode | Scénario Métier | Piliers Lughus Démontrés |
| :--- | :---: | :--- | :--- |
| [`data_ingestion_agent/`](data_ingestion_agent/) | **Ep. 1** | Ingestion SQL & requêtage analytique Zero-Leak sur base SQLite | Connexion `mode=ro`, isolation par schéma, masquage `SafeToolError`, outils en lecture seule. |
| [`code_interpreter_agent/`](code_interpreter_agent/) | **Ep. 2** | Analyste de données & interpréteur Python confiné dans un conteneur OCI | Sandbox OCI Docker/Podman fail-closed, digest SHA-256 immuable, `--network=none`, quotas CPU/RAM/PIDs, export d'artefacts. |

---

## 🚀 Parcours de Démarrage Universel

Tous les agents du catalogue suivent une convention de lancement et d'interaction unifiée :

### 1. Accéder au dossier de l'agent
```bash
cd examples/<nom_de_l_agent>
```

### 2. Configurer l'environnement local
Copiez le modèle de configuration fourni et renseignez vos clés de fournisseur LLM (compatible tout fournisseur supporté par LiteLLM : OpenAI, Anthropic, Mistral, Ollama, Gemini, etc.) :
```bash
cp .env.example .env
```

Variables minimales recommandées :
```bash
export AGENT_MODEL="openai/gpt-4o"
export OPENAI_API_KEY="sk-..."
export ENABLE_CONSOLE="true"  # Active la console de débogage web
```

### 3. Installer les dépendances et démarrer le serveur
Grâce à `uv`, l'agent s'installe et se lance en une seule commande isolée :
```bash
uv run --extra dev python -m <nom_de_l_agent>
```

### 4. Interagir avec l'Agent
Une fois le serveur démarré, les interfaces standardisées suivantes sont immédiatement disponibles :
- 🖥️ **Developer Console Web :** `http://127.0.0.1:<PORT>/ui` (interface graphique pour tester des prompts, inspecter les appels d'outils et visualiser les métadonnées).
- 📜 **A2A Agent Card :** `http://127.0.0.1:<PORT>/.well-known/agent-card.json` (carte de métadonnées et de compétences publiable selon le standard A2A).
- 🔌 **Endpoint RPC A2A :** `POST http://127.0.0.1:<PORT>/` (transport JSON-RPC / Server-Sent Events pour la communication agent-à-agent).

---

## 🧪 Validation Locale & Tests Hors-Ligne

Pour garantir une intégrité absolue et un déploiement continu fluide, chaque agent inclut des tests unitaires déterministes fonctionnant sans réseau :

```bash
cd examples/<nom_de_l_agent>
uv run --extra dev pytest tests -v
```

Les tests vérifient :
- La validité et la conformité des schémas d'outils Pydantic ;
- L'isolation et le respect des bornes de sécurité (blocage réseau, timeouts, quotas) ;
- Le bon fonctionnement des mécanismes de repli et de masquage d'erreurs (`SafeToolError`) ;
- L'exactitude du calcul budgétaire (tokens, appels d'outils).

---

## 📐 Anatomie Canonique d'un Agent Lughus

Tout nouvel agent ajouté au catalogue doit strictement respecter l'arborescence suivante :

```
examples/<mon_agent>/
├── <mon_agent>/
│   ├── __init__.py           # Exports publics du package
│   ├── __main__.py           # Point d'entrée de service, AgentCard A2A & serve(app)
│   ├── config.py             # Settings héritant de BaseSettings avec validation stricte
│   ├── gateway.py            # Sous-classe de BaseGateway pour le routage A2A
│   ├── tools.py              # ToolRegistry local, outils typés et SafeToolError
│   └── workspace.py          # Session request-scoped, agent_loop et gestion du budget
├── tests/
│   ├── __init__.py
│   ├── test_gateway.py       # Tests d'intégration A2A avec MockLLM
│   └── test_tools.py         # Tests unitaires des outils métier
├── .env.example              # Modèle de variables d'environnement exhaustif et commenté
├── pyproject.toml            # Configuration du package, dépendances et scripts
└── README.md                 # Documentation exhaustive (Plan Canonique en 9 Piliers)
```

---

## 🛡️ Règles d'Hygiène Git & Bonnes Pratiques

Afin de préserver la propreté du dépôt :
- **Secrets & Environnements :** Ne jamais commiter de fichiers `.env`, clés privées ou jetons.
- **Artefacts & Caches :** Les répertoires `.venv/`, `artifacts/`, `__pycache__/`, `*.egg-info/` et `uv.lock` des exemples sont systématiquement exclus par [`examples/.gitignore`](.gitignore).
- **Reproductibilité :** Tout code doit être fonctionnel avec Python `>=3.11` et validé par `ruff` et `mypy`.
