# Knowledge MCP

Indicizza i documenti di una cartella e li rende ricercabili tramite un server MCP. L'app gira con Docker insieme a Qdrant e si gestisce da una WebUI locale. I documenti restano sul tuo computer: il container li monta in sola lettura.

## Avvio con Docker

Serve Docker con il plugin Compose e una cartella già esistente che contiene i documenti.

1. Scarica il repository e apri la sua cartella:

   ```bash
   git clone https://github.com/paoloronco/ai-knowledgeagent-mcp.git
   cd ai-knowledgeagent-mcp
   ```

2. Crea un file `.env` nella stessa cartella di `compose.yaml`, indicando il percorso **assoluto** dei documenti:

   ```dotenv
   KNOWLEDGE_HOST_PATH=/home/utente/Documenti
   ```

   Su Windows usa, per esempio, `KNOWLEDGE_HOST_PATH=C:/Users/Paolo/Documents`. Il percorso deve esistere prima dell'avvio.

3. Scarica l'immagine pubblica e avvia l'app:

   ```bash
   docker pull paoloronco/knowledge-mcp:latest
   docker compose up -d
   ```

Apri la **WebUI** su [http://127.0.0.1:8080](http://127.0.0.1:8080). Da lì puoi provare l'indicizzazione su 10 documenti, avviare quella completa, modificare la policy, scegliere una sottocartella, programmare gli aggiornamenti e accendere o spegnere il server MCP. Prima di indicizzare, controlla la [policy predefinita](knowledge-mcp/mcp/index-policy.yaml): alcune cartelle riservate sono sempre escluse.

Quando è attivo, l'endpoint MCP è `http://127.0.0.1:8000/mcp`. È un endpoint per client MCP, non una pagina da aprire nel browser.

## Aggiornamento e dati

Per scaricare una nuova versione:

```bash
git pull
docker pull paoloronco/knowledge-mcp:latest
docker compose up -d
```

Qdrant, stato dell'indicizzazione, policy e cache del modello sono conservati in volumi Docker. `docker compose down` ferma l'app senza cancellarli; **`docker compose down -v` li elimina**, incluso l'indice già creato. La cartella dei documenti è montata in sola lettura e non viene cancellata da questi comandi. Per cambiarla, modifica `KNOWLEDGE_HOST_PATH` nel file `.env` e riavvia con `docker compose up -d`.

WebUI e MCP sono esposti solo su localhost e non hanno un login integrato. Per usarli da remoto serve un proxy autenticato; vedi la [guida alla sicurezza](docs/security-model.md). Qdrant non è esposto all'host.

## Codice e documentazione

- [Servizio, ingestion e avvio manuale con Python](knowledge-mcp/README.md)
- [Architettura e comportamento della ricerca](docs/README.md)
- [Esempi di integrazione con client AI](AI/README.md)
- [Workflow che pubblica l'immagine su Docker Hub](.github/workflows/docker.yml)

Questo repository non contiene documenti privati, credenziali o dati Qdrant. Non ha ancora un file LICENSE.
