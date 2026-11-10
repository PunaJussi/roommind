# PunaJussi-forkki

Tämä repositorio on julkinen forkki virallisesta RoomMindistä (`snazzybean/roommind`). Tarkoitus on pitää **Gradual thermostat** (asetepisteramppi) tallessa, kun virallinen versio päivittyy.

| | |
|---|---|
| Forkki | https://github.com/PunaJussi/roommind |
| Asennettu versio | 1.8.2.4 |
| Virallinen pohja | v1.8.2 |
| HA-kohde | `/homeassistant/custom_components/roommind` |

## Mitä ei saa tehdä

- Älä asenna Home Assistantin Marketplace/HACS-päivitystä virallisesta RoomMindistä. Entiteetti `update.roommind_update` on kytketty pois, jotta se ei ylikirjoita tätä asennusta.
- Älä työnnä koodia `snazzybean/roommind`-repositorioon (Cursorsin Publish Branch tekee sen).

Home Assistantin omat päivitykset (Core, OS, Supervisor) saa asentaa normaalisti.

## Kun virallisesta RoomMindistä tulee uusi versio

Kerro Cursor-agentille. Se hakee muutokset `upstreamista`, säilyttää Gradual thermostat -koodin, nostaa fork-version (esim. 1.8.3 → 1.8.3.1) ja siirtää tiedostot Home Assistantiin SSH:lla.

Gradual thermostat -käyttöohje: [control-and-devices.md](control-and-devices.md).
