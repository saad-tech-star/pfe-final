# 🚀 GUIDE OPTIMISATION IA IMACAB
# Fichier : ollamaAi_optimisations.md

## ⚡ Problème : IA trop lente (10 minutes)

### Causes fréquentes et solutions

---

## 1. Timeout Ollama (solution immédiate)

Dans `ollamaAi.py`, ajouter un timeout sur chaque appel :

```python
import ollama

# ✅ CORRECTION : ajouter timeout à chaque appel ollama.chat()
resp = ollama.chat(
    model='mistral',
    messages=[...],
    options={
        'temperature': 0.0,
        'num_predict': 200,     # ← Limiter la longueur de réponse
        'num_ctx': 2048,        # ← Réduire la fenêtre de contexte
    },
    # timeout=30,             # Uncomment if your ollama version supports it
)
```

---

## 2. Cache des réponses fréquentes

Ajouter dans `ollamaAi.py` :

```python
from functools import lru_cache
import hashlib

# Cache des réponses en mémoire (expire au redémarrage)
_response_cache = {}

def _get_cache_key(msg: str, role: str) -> str:
    return hashlib.md5(f"{role}:{msg.lower().strip()}".encode()).hexdigest()

def generer_sql(user_msg: str, user_role: str = 'operateur'):
    # Vérifier le cache pour les questions identiques
    cache_key = _get_cache_key(user_msg, user_role)
    if cache_key in _response_cache:
        logger.info("✅ Réponse depuis le cache")
        return _response_cache[cache_key]
    
    # ... (logique existante) ...
    
    # Sauvegarder dans le cache (sauf erreurs)
    if result and not isinstance(result, dict):
        _response_cache[cache_key] = result
    
    return result
```

---

## 3. Vérifier si Ollama est démarré

```bash
# Vérifier le statut
ollama serve

# Lister les modèles installés
ollama list

# Tester directement
curl http://localhost:11434/api/generate -d '{
  "model": "mistral",
  "prompt": "Bonjour",
  "stream": false
}'
```

---

## 4. Utiliser un modèle plus rapide

```bash
# Mistral 7B est recommandé (équilibre vitesse/qualité)
ollama pull mistral

# Pour encore plus rapide (moins précis)
ollama pull phi3:mini

# Dans ollamaAi.py, changer le modèle :
# model='phi3:mini'   ← plus rapide
# model='mistral'     ← recommandé
# model='llama3'      ← plus puissant mais lent
```

---

## 5. Réponse rapide pour les salutations (déjà implémenté)

```python
# Dans ollamaAi.py — le fallback sans IA est déjà là
if _is_greeting(user_msg):
    try:
        resp = ollama.chat(...)
        return resp['message']['content']
    except Exception:
        # ✅ Fallback instantané si Ollama down
        return "Bonjour ! Comment puis-je vous assister ?"
```

---

## 6. Architecture async (avancé)

Pour la production, utiliser `asyncio` avec Flask :

```python
# Installer : pip install flask[async] aiohttp
# Dans app.py :
@app.route('/chat', methods=['POST'])
async def chat():
    # ... utiliser await avec async ollama client
```

---

## 7. Diagnostic rapide

```python
# Ajouter dans ollamaAi.py pour mesurer le temps :
import time

def generer_sql(user_msg, user_role='operateur'):
    t0 = time.time()
    # ... logique ...
    logger.info(f"⏱️ Temps de réponse : {time.time()-t0:.2f}s")
    return result
```

---

## ✅ Actions recommandées immédiatement

1. `ollama serve` → démarrer le serveur local
2. `ollama pull mistral` → télécharger le modèle
3. Ajouter `num_predict: 200` dans les options → réponses plus courtes et rapides
4. Activer le cache en mémoire → éviter de recalculer les mêmes questions
5. Le fallback texte des salutations → "Bonjour" répond instantanément même si Ollama est lent
