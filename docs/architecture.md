# Architectuur

GhostSketch gebruikt React, TypeScript en React Flow voor de interface, FastAPI voor de lokale API en SQLite voor de gegevens. De backend levert ook de gebouwde frontendbestanden. `npm start` gebruikt één lokaal adres: 127.0.0.1:8000.

## Gegevens en herstel

Projecten bevatten sessies, transcriptfragmenten, kaarten, verbindingen en onderzoeksvragen. Iedere wijziging bevat de laatst bevestigde revisie. SQLite schrijft atomisch; een verouderde revisie geeft409 en overschrijft geen nieuwer werk. Unieke aanvraag-IDs maken herhaalde tekst- of audio-import idempotent. De vragenlijst, bronpanelen en terugblik gebruiken dezelfde gegevens als het bord.

## Ordenen en spraak

De standaard gebruikt lokale Nederlandse tekstregels, herkenbaar als regelverwerking. Optioneel kan een eigen lokaal Ollama-model gecontroleerde kaartvoorstellen leveren. Modeluitvoer herschrijft geen bestaande kaarten. Bij een modelprobleem blijft het transcript behouden en volgt een melding; er is geen stille cloudfallback.

De browser vraagt pas na Start om microfoontoegang. Een AudioWorklet verzamelt PCM en de client maakt zelfstandige WAV-fragmenten. Upload is sequentieel en begrensd. Stoppen geeft de microfoon direct vrij; verwerking van eerder opgenomen fragmenten blijft apart zichtbaar. Een eigen lokale whisper.cpp-server doet de transcriptie. ffmpeg is optioneel voor andere telefoonformaten. Tijdelijke audio wordt na verwerking verwijderd.

## Onderzoek en netwerk

De gebruiker keurt de exacte zoektekst goed en opent zelf een browserzoekopdracht. Bronnen en passages worden handmatig geregistreerd. Er is geen autonome webophaler. De server valideert Host en Origin en gebruikt een willekeurig token voor wijzigingen. Modeladressen zijn uitsluitend loopback-HTTP. Er is geen cloudaccount of standaardtelemetrie.

## Vervolg

Test Nederlandse modelkwaliteit en snelheid eerst op de doelcomputer. Automatische bronverzameling, samenwerking, sprekerherkenning, gesproken antwoorden en een desktopinstaller volgen als afzonderlijke uitbreidingen. Zie het [ontwikkelplan](https://chatgpt.com/space/page_ac25849d720c8191b497795c05638f25) en het [API-contract](api-contract.md).

## Govern en notitiepagina's

Govern archiveert audiobronnen en transcribeert ze. `govern.py` leest alleen de
servergeconfigureerde lokale feed met een backend-token; de browser krijgt geen
Govern-cookie, sleutel of SQL-toegang. GhostSketch bewaart eigen notitieboeken en
herleidbare transcriptkopieën in SQLite. Geen ruwe audio via deze verbinding.

De bestaande Project/Session-modellen blijven compatibel: Project is het
notitieboek; Session is een pagina met `section`, `page_text`, `strokes` en een
optionele `govern_recording`-identiteit. Oude documenten krijgen defaults zonder
conversie of dataverlies. Een bronidentiteit bevat verbinding, opname-ID en checksum;
fragmentaanvragen hebben stabiele hashes. Herhalen bewaart bestaande notities,
revisies, afwijzingen en tekeningen. Bronfragmenten worden vóór ordening opgeslagen.
Een bronfout maakt geen pagina; een organizerfout bewaart tekst met een melding.
Eigen correcties horen in de pagina; gekoppelde transcripttekst is onveranderlijk.
`NotebookPage` is de standaardweergave. Het bestaande React Flow-bord blijft een
alternatieve weergave van dezelfde kaarten en verbindingen.
