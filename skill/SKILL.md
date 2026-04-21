---
name: rca-orchestrator
description: >
  Pilota il sistema Remote Control Agent (RCA) per deployare, monitorare e
  gestire componenti applicativi su macchine Linux e, dalla Fase 3, cluster
  Kubernetes. Usala quando l'utente chiede di modificare configurazioni di
  deployment, lanciare/fermare/riavviare componenti, verificare lo stato di
  deploy, leggere log o metriche, eseguire test di componenti, effettuare
  rollback. La skill si appoggia al server MCP esposto dal control plane
  RCA.
---

# RCA Orchestrator Skill

Questa skill guida un agente AI nell'uso del server MCP del control plane
RCA. È pensata per ridurre il consumo di token esponendo un modello mentale
chiaro e un flusso operativo standardizzato.

> Nota: questo è lo **skeleton** prodotto in Fase 0. Sarà arricchito in
> Fase 2 con flussi decisionali completi e in Fase 3 con sezioni dedicate
> a Kubernetes, RBAC e workflow avanzati.

## Modello mentale

Il sistema RCA gestisce progetti descritti da un file `deployment.yaml` che
enumera **hosts** (dove deployare) e **components** (cosa deployare), con
un piano di assegnazione `deployment[]`. Ogni componente ha un `deploy_mode`
(`cold`, `hot`, `blue_green`) e si accompagna a `healthcheck` e, opzionalmente,
a `tests`.

Tre attori:

1. **Control plane** (Python): legge lo YAML, ordina le operazioni, parla
   ai daemon.
2. **Daemon** (`rcad`, Go): un processo residente su ogni host che conosce
   lo stato locale e esegue le azioni richieste.
3. **Agente (tu)**: operi via server MCP del control plane.

## Verbi MCP disponibili

Interrogali tramite il tool `list_tools` dell'MCP se incerto. In Fase 1:

| Tool | Input | Output |
|------|-------|--------|
| `list_hosts` | — | Array di host con status, tag, componenti assegnati |
| `get_state` | `project?` | Stato aggregato di tutti i componenti |
| `get_component_state` | `component_id` | Stato dettagliato del singolo |
| `validate_config` | `yaml_text` | OK o lista errori con path e messaggio |
| `apply_config` | `yaml_text, dry_run?` | Diff + conferma applicazione |
| `deploy` | `project?, component_id?` | Avvia deploy sincrono o async |
| `start` / `stop` / `restart` | `component_id` | Esito operazione |
| `tail_logs` | `component_id, lines?` | Array di righe |

Dalla Fase 2 si aggiungono: `rollback`, `run_tests`, `get_deployment_history`,
`get_metrics`, `drift_status`.

## Flusso operativo standard

Il flusso raccomandato per **ogni modifica** alla configurazione:

1. **Validate**. Chiama `validate_config` con lo YAML proposto. Se ci sono
   errori, correggili prima di procedere; **non** passare a `apply_config`
   finché la validazione non è pulita.
2. **Diff**. Chiama `apply_config` con `dry_run: true`. Mostra all'utente
   quali componenti saranno creati, modificati, rimossi.
3. **Conferma**. Attendi conferma esplicita dell'utente prima di applicare.
4. **Apply**. Chiama `apply_config` con `dry_run: false`. Ricevi un handle
   del deploy.
5. **Watch**. Esegui poll di `get_state` (ogni 2-5s) finché tutti i
   componenti impattati sono in stato terminale (`running`, `failed`).
6. **Verify**. Leggi eventuali healthcheck falliti o log d'errore;
   riporta un sommario all'utente.
7. **Rollback** (se necessario): solo se il risultato è insoddisfacente e
   l'utente lo chiede esplicitamente, invoca `rollback` (Fase 2+).

## Gestione errori

Gli errori dal server MCP hanno forma:

```json
{
  "code": "build_failed",
  "message": "npm ci exited with code 1",
  "details": { ... },
  "suggested_fix": "install libpq-dev on host"
}
```

Azioni raccomandate per codice (elenco iniziale — sarà ampliato):

- `validation_error` → mostra gli errori path-per-path all'utente; non
  ritentare.
- `auth_error` (Git/registry) → verifica credenziali nel vault, chiedi
  all'utente di aggiornarle se mancanti.
- `dependency_missing` → se `suggested_fix` propone un `apt install`,
  riporta l'istruzione all'utente (in Fase 1 l'agente non esegue
  comandi shell sull'host).
- `healthcheck_failed` → leggi i log (`tail_logs`), estrai le ultime righe
  d'errore, proponi un rollback.
- `timeout` → aumenta `timeout_sec` se plausibile, oppure segnala
  potenziale blocco.
- `conflict` → lo stato attuale impedisce l'azione; leggi prima lo stato.
- `not_found` → verifica che l'`id` esista.

## Convenzioni d'uso token-efficient

1. **Non scaricare log interi**. Usa `tail_logs` con `lines: 50-200`. Se
   serve di più, chiedi un filtro per livello o timestamp.
2. **Non fare poll aggressivo**. Intervallo 3-5 secondi basta.
3. **Comprimi lo stato**. Se mostri lo stato all'utente, riassumi (es.
   "3/3 componenti running, healthcheck OK") invece di dumpare il JSON.
4. **Errori prima del resto**. Se un tool ritorna errore, analizzalo
   subito; non procedere nel flusso come se fosse andato bene.

## Anti-pattern

- **Non** editare direttamente i file sul disco dei daemon via altri
  canali (SSH, ecc.). Tutto passa per il control plane.
- **Non** avviare un `deploy` senza aver prima fatto `validate_config` e
  aver mostrato il diff all'utente.
- **Non** chiamare `start`/`stop` ripetutamente come surrogato di
  restart: usa `restart` direttamente.

## Esempi di dialogo

**Utente**: "Aggiungi un secondo componente redis al progetto demo e
deployalo su host1."

1. `get_state` → capisco cosa c'è.
2. Propongo all'utente uno YAML aggiornato che aggiunge il componente
   `cache` con `source.type: docker, image: redis`.
3. `validate_config` con lo YAML proposto.
4. `apply_config` con `dry_run: true` → mostro diff ("+ cache").
5. Conferma utente.
6. `apply_config` con `dry_run: false`.
7. Poll `get_state` finché `cache` è running.
8. Sommario: "cache deployato, healthcheck verde."

**Utente**: "Il servizio API non risponde."

1. `get_component_state component_id=api`.
2. Se `status: failed` o `healthcheck` failing: `tail_logs api lines=100`.
3. Analizzo le ultime righe; se pattern noto (es. "connection refused to
   database"), riporto la causa.
4. Propongo `restart` o, in Fase 2+, `rollback` all'ultima versione green.

## Evoluzione

Questo documento cresce con il prodotto:

- **Fase 1**: questo skeleton.
- **Fase 2**: aggiungere sezioni su test, rollback, hot deploy, canary,
  git-sync, vault.
- **Fase 3**: aggiungere Kubernetes, RBAC, observability, workflow multi-ambiente.
