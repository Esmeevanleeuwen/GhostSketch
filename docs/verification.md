# Verificatie van versie 0.1.0

Gecontroleerd op 5 november 2026 met Python 3.12, Node.js 24 en Chromium op Linux.

## Automatische controles

- `npm run check`: strict TypeScript geslaagd.
- `npm test`: 52 backendtests en 13 frontendtests geslaagd.
- `npm run build`: productiebuild geslaagd.

De tests controleren onder meer SQLite-herstart, revisieconflicten, idempotente invoer, echte datumvalidatie, bronverwijzingen, JSON-herstel met nieuwe IDs, lokale API-toegang, upload- en projectgrenzen, modelantwoorden, behoud van oorspronkelijke tekst, audio-opruiming en WAV-opnamegedrag.

## Browser naar opslag

Een verse tijdelijke database is met de productiefrontend en de echte lokale HTTP-service doorlopen:

1. Project maken, Nederlandse notitie importeren en vier kaartvoorstellen met bronverwijzing ontvangen.
2. Voorstel bewaren, ongedaan maken, positie wijzigen en de opgeslagen toestand na herladen terugvinden.
3. Sessie afronden en de terugblik bekijken.
4. Exacte zoektekst controleren en toestemming vastleggen. Voor toestemming staat er geen zoeklink; de test opent geen externe pagina.
5. Een echte bronlink en zelf ingevoerde passage bewaren.
6. JSON en Markdown downloaden. JSON in een nieuw schetsboek herstellen met correct opnieuw gekoppelde kaart-, bron- en vraag-IDs.
7. Mobiele navigatie en werkruimte op 360 en 390 pixels controleren.

Hierbij zijn geen JavaScript-fouten of onverwachte externe netwerkverzoeken waargenomen.

## Microfoon en lokale modelprotocollen

Chromium is met een synthetisch audioapparaat gebruikt. Voor Start werd geen microfoon geopend. Na starten maakte de AudioWorklet een zelfstandig 16 kHz mono PCM16 WAV-fragment, dat via de echte API bij een lokale whisper-protocolmock aankwam. Pauzeren gaf alle audiotracks vrij en de teruggestuurde tekst verscheen als drie kaartvoorstellen. Ook het Ollama-pad is via de echte interface, API en een lokale protocolmock doorlopen.

Dit controleert opnamelevenscyclus en API-integratie. Er zijn geen echte modelgewichten gedownload. Nederlandse herkenningskwaliteit, reactietijd, geheugengebruik, fysieke microfoons en Windows zijn nog op de doelcomputer te toetsen.

## Opnieuw controleren

```sh
npm run setup
npm run check
npm test
npm run build
npm start
```

De lokale tests maakten uitsluitend eigen tijdelijke testgegevens; gebruikersgegevens en modelgewichten horen niet in Git.
