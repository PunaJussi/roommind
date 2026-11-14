# PunaJussi-forkki

Tämä repositorio on julkinen forkki virallisesta RoomMindistä (`snazzybean/roommind`). Tarkoitus on pitää **Gradual thermostat** (asetepisteramppi) tallessa, kun virallinen versio päivittyy.

| | |
|---|---|
| Forkki | https://github.com/PunaJussi/roommind |
| Asennettu versio | 1.8.2.11 |
| Virallinen pohja | v1.8.2 |
| HA-kohde | `/homeassistant/custom_components/roommind` |

## 1.8.2.11

- Manuaalinen ILP-setpoint (kaukosäädin / MelCloud / HA) korvaa Gradualin held-arvon kuin RoomMind olisi asettanut sen; adjustment-intervalli nollautuu. Huoneen tavoite ei muutu (`follow_device_setpoint` edelleen erillinen optio).
- Coordinator `UPDATE_INTERVAL` 30 → **120** s (ohjaussilmukan tarkistusväli; Gradual-askel edelleen laitteen Adjustment interval).
- Käyttäjädok: [control-and-devices.md](control-and-devices.md) — *Changes Made on the Device* / *Gradual thermostat*.

## 1.8.2.10

- **Never idle / Keep heat when outdoor is cold** pitävät vain `heat`/`cool`-moodin — eivät kirjoita setpointeja. Gradual thermostat omistaa lämpötilan (korjaa A↔B-pingiksen idle-jaksoissa).
- Fan speed: Default / Room Occupied / Override (entity-OR); coil dry voittaa kuivauksen ajan.
- Gradual offset-max 5 °C; UI vain englanniksi.

## Mitä ei saa tehdä

- Älä asenna Home Assistantin Marketplace/HACS-päivitystä virallisesta RoomMindistä. Entiteetti `update.roommind_update` on kytketty pois, jotta se ei ylikirjoita tätä asennusta.
- Älä työnnä koodia `snazzybean/roommind`-repositorioon (Cursorsin Publish Branch tekee sen).

Home Assistantin omat päivitykset (Core, OS, Supervisor) saa asentaa normaalisti.

## Kun virallisesta RoomMindistä tulee uusi versio

Kerro Cursor-agentille. Se hakee muutokset `upstreamista`, säilyttää Gradual thermostat -koodin, nostaa fork-version (esim. 1.8.3 → 1.8.3.1) ja siirtää tiedostot Home Assistantiin SSH:lla.

Gradual thermostat -käyttöohje: [control-and-devices.md](control-and-devices.md).

Forkissa UI on vain englanniksi (`frontend/src/locales/en.json`). Älä palauta `de`/`fr`/`it`-käännöksiä upstream-mergessä.

## Compressor run sensor (Tehomittari)

RoomMindin `climate.mitsu` käyttää `compressor_run_sensor`: **`sensor.ilmalampopumppu_energy_period`** (arvo alle 1 = kompressori pois).

Tasmota Sonoff Pow R2 (`84:cc:a8:95:a1:4e`, topic `tasmota_95A14E`) julkaisee `ENERGY.Period` live-telemetriassa (`tele/tasmota_95A14E/SENSOR`), mutta **ei** discovery-listassa (`tasmota/discovery/…/sensors`). HA:n Tasmota-integraatio poistaa restartissa entiteetit, joita listassa ei ole — siksi Period katosi yön Core-restarteissa.

**Pysyvä korjaus (käytössä):** MQTT discovery -sensori (retained), ei Tasmota-platformia:

| | |
|---|---|
| Entiteetti | `sensor.ilmalampopumppu_energy_period` |
| Discovery-topic | `homeassistant/sensor/tasmota_95A14E_energy_period/config` |
| State-topic | `tele/tasmota_95A14E/SENSOR` |
| Value template | `{{ value_json.ENERGY.Period }}` |
| unique_id | `mqtt_84CCA895A14E_energy_period` |

Älä:

- lisää Periodia käsin retained `tasmota/discovery/…/sensors` -listaan (rediscovery / orphan-siivous poistaa sen)
- korvaa Periodia Power≥W -templatella (väärä signaali lyhyissä tehodippeissä)
- asenna virallista RoomMindiä HACS:sta tämän päälle
