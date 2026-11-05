# GhostSketch

Een lokaal schetsboek dat met je gesprek meegroeit. Bewaar ideeën, vragen, acties en besluiten op een whiteboard, met de oorspronkelijke woorden erbij.

GhostSketch is een **lokale eerste versie**, met een React-interface en een Python-service met SQLite. De app begint leeg. Je kunt meteen schetsboeken maken, tekst importeren, kaartvoorstellen controleren en je werk bewaren. Er is een expliciet te laden voorbeeld, als je eerst wilt rondkijken.

## Starten

Je hebt **Node.js 22.12 of nieuwer**, **npm** en **Python 3.11 of nieuwer** nodig. Windows en Linux gebruiken dezelfde opdrachten:

```sh
git clone https://github.com/Esmeevanleeuwen/GhostSketch.git
cd GhostSketch
npm run setup
npm start
```

Open daarna **http://127.0.0.1:8000**. Stop de app met Ctrl+C. De installatie haalt softwarepakketten op, maar geen spraak- of taalmodellen. Na installatie en build heeft de basis geen internet nodig.

Ontwikkelen met automatische frontendupdates:

```sh
npm run dev
```

Open http://127.0.0.1:5173. De Vite-client stuurt API-verzoeken door naar de lokale Python-service op poort 8000.

## Wat werkt

- Schetsboeken en sessies aanmaken en heropenen, met lokale SQLite-opslag.
- Kaarten bewerken, bewaren, afwijzen, verplaatsen en verbinden op het whiteboard; wijzigingen ongedaan maken.
- Gespreksfragmenten en tijdstippen terugvinden via de bron van een kaart.
- Telefoonnotities als tekst importeren en voorstellen beoordelen.
- JSON-import en export, plus Markdown-export van je eigen gegevens.
- Open vragen voorbereiden voor onderzoek, de exacte zoektekst goedkeuren en bewust in je browser zoeken.
- Echte bronlinks en bronpassages handmatig aan een onderzoeksvraag toevoegen.
- Sessieterugblik en instellingen afgeleid van je opgeslagen gegevens.

De standaardordening gebruikt **lokale Nederlandse tekstregels**. Dit is herkenbaar als regelverwerking, geen taalmodel. Voor automatische AI-ordening kun je een eigen lokaal Ollama-model aansluiten.

## Optionele lokale AI en spraak

### Ollama

Installeer Ollama en download zelf een geschikt klein meertalig model. Laat Ollama uitsluitend lokaal luisteren. Open Instellingen in GhostSketch, controleer de verbinding, kies een geïnstalleerd model en schakel de ordening om naar Ollama. Modeluitvoer wordt gecontroleerd voordat voorstellen op het bord komen. Modelkwaliteit en snelheid moet je op je eigen computer beoordelen.

### whisper.cpp

Start een eigen `whisper-server` met een meertalig model op **127.0.0.1:8081**. GhostSketch gebruikt de lokale `/inference`-API. Er is geen cloudspraakfallback en de app downloadt geen modellen.

Wanneer de service beschikbaar is, kun je een opname importeren of na een bewuste start de computermicrofoon gebruiken. De browser maakt zelfstandige WAV-fragmenten. Pauzeren of stoppen geeft de microfoon direct vrij; reeds ontvangen fragmenten kunnen nog worden verwerkt.

WAV is de basisroute. Voor andere telefoonformaten zoals M4A moet **ffmpeg** op het systeem beschikbaar zijn. Ruwe opnames worden tijdelijk verwerkt en daarna verwijderd; deze versie archiveert geen audio.

Je Action- of HEMA-speaker is voor geluidsweergave. Of hij ook als microfoon werkt hangt af van het model en de computer. Je kunt altijd beginnen met telefoonnotities plakken.

### Andere lokale poorten of gegevensmap

Kopieer `.env.example` naar `.env` en pas de lokale adressen of `GHOSTSKETCH_DATA_DIR` aan. Alleen loopbackadressen zijn toegestaan voor de modelservices. De start- en ontwikkelscripts lezen `.env`; zet dit bestand niet in Git.

## Onderzoek

Deze versie heeft **geen autonome zoekagent**. Je bekijkt en bevestigt de zoektekst en opent daarna zelf de browserzoekopdracht. Een zoekdienst ontvangt de zoektekst en netwerkgegevens zoals je IP-adres. GhostSketch stuurt geen volledig transcript of audio naar een zoekdienst. Je voegt zelf de gevonden bron en relevante passage toe. Een bewaarde bevinding is niet automatisch een bewezen feit.

## Opslag en privacy

Projecten en instellingen worden lokaal opgeslagen. De opslaglocatie is via `GHOSTSKETCH_DATA_DIR` instelbaar. Bewaar exports als back-up. Het JSON-formaat bevat je transcript, kaarten en bronnen; behandel zulke bestanden als privégegevens. De app versleutelt de database niet zelf.

De HTTP-service luistert op 127.0.0.1. De app controleert Host en Origin en beschermt wijzigingen met een willekeurig sessietoken. Er is geen account, cloudopslag of standaardtelemetrie.

## Grenzen van de eerste versie

Een schetsboek mag maximaal 7 MiB aan opgeslagen gegevens bevatten. Geplakte notities mogen tot 50.000 tekens bevatten; voor één Ollama-verzoek geldt 16.000 tekens. Audio-import accepteert maximaal 25 MiB en 30 minuten per bestand. Als een grens wordt bereikt, blijft de laatst bevestigde versie behouden. Verdeel langere gesprekken of notities over meerdere sessies of schetsboeken.

## Controleren

```sh
npm run check
npm test
npm run build
```

De repository bevat tests voor opslag, bronverwijzingen, revisieconflicten, herhaalde import, lokale modeladapters en de frontendlogica. Microfoonkwaliteit en de snelheid van echte modelgewichten blijven afhankelijk van je hardware.

## Ontwerp en ontwikkeling

- [Interactief UX/UI-ontwerp](docs/design/interactive-design.html), als zelfstandig bestand te openen.
- [Volledig ontwerp en PDF-schermenboek](https://chatgpt.com/space/page_58e19c22f0548191bb81968403afce78), beschikbaar in het bijbehorende ChatGPT-account.
- [API-contract](docs/api-contract.md).
- [Verificatie van de eerste versie](docs/verification.md).
- [Architectuur en vervolgstappen](docs/architecture.md).

De eerste versie richt zich op één lokale gebruiker. Samenwerking tussen computers, gesproken antwoorden, betrouwbare sprekerherkenning en automatisch brononderzoek zijn vervolgstappen.
