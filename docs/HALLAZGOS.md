# Hallazgos de los colaboradores

Datos sacados en el coche y en los firmwares por quienes han contribuido al
proyecto (tester del Z4 E89, Cars Done con el E60 LCI, puerto F30, E9x LCI con C16A). Entre
corchetes, el commit. Los apartados marcados *(PR #4)* están en la rama
`contrib-z4-patches`, todavía no fusionada en `main`.

## 1. GPS / posición del CIC → teléfono  [96327af] *(PR #4)*
- El CIC calcula posición por dead reckoning (velocidad de ruedas + giróscopo):
  estable en túneles/parkings donde el GPS del móvil falla.
- Se obtiene vía RHMI: en `AAPlugin.xml` → `<raDataRequestModel id="230" modelType="vehicle.location"/>`
  (proveedor `CLocationProvider` en HmiMain 9283417A).
- Otros modelos disponibles en la misma lista: `vehicle.speed`, `vehicle.acceleration`,
  `vehicle.mileage_in_km`, `vehicle.tankrange`, `mmi.units`.
- Handler registrado en create; `activateDataUpdate` en Connect (como apps Today/PIM).
- Valor: wide string `"lat,lon"` en unidades CIC (2^32 = 360°), ~1 Hz. `"0,0"` tras arranque = ignorar.
- Símbolos por dlsym: `PluginApp::addDataUpdateHandler/activateDataUpdate`, `Parcel::readWString`,
  `BasicString<unsigned short>`; si falta uno solo se desactiva la función.
- libcicaa: anuncia sensor LOCATION (1); input `CICAA_IN_LOCATION (9)` → SensorEvent LocationData
  {ts, lat_e7, lon_e7, accuracy 10 m}, solo con vídeo activo. Conversión: `e7 = (raw * 1.8e9) >> 31`.

## 2. Teclas skip volante / panel → teléfono  [80580c9] *(PR #4)*
- HmiMain exporta por nombre clases proxy de teclas. Se parchea entrada 8 de vtable (handler) en
  `CPxyControlElementsMFL::CSearchSwitch1` (volante) y `CPxyCECenterStack::CPushButtonSkip` (|<< >>| panel).
- Solo cambia un word de la vtable escribible (sin código). Llama al original primero.
- Estado por getter: 1/2 pulsado, 0 suelto, cada estado llega 2 veces. Volante 1 = next, panel 1 = previous.
- Se envía KEYCODE_MEDIA_NEXT (87)/PREVIOUS (88). Hook en Connect (no create → sin boot loop),
  verificado contra 12 bytes del getter; `aap_destroy()` restaura.

## 3. DSP DM642 (dvd_dm642.bin) *(PR #4)*
- Base: ver [ARQUITECTURA.md](ARQUITECTURA.md#notas-de-ingeniería-inversa-del-dsp).
- **Ring de 1 MiB** de elementary stream [7124786]: NAL que cruza el wrap se decodifica mal
  (freeze/artefactos, AVP_EVENT_ERROR cada 1-2 min). Fix: si un frame acaba en los últimos 60 KB,
  añadir filler NAL (tipo 12) que pase 4 KB del límite. Padding exacto al límite NO bastó.
- **Contador de skip tras frame tardío** [5820c50]: tercer parche en file 0x09ba68 / DSP 0x81f1bd34:
  `stw A0,*A3` (0x000c0275) → NOP con bit paralelo (0x00000001). AA solo manda frames si cambia la
  imagen → antes se congelaba (logs "skip frame" con 39).
- **Deriva de reloj** [55e0b25]: DSP muestra a su reloj, el móvil entrega más rápido → +~1 ms/s de
  retraso (≈1 s, freeze a ~20 min). Desplazar PTS no sirve. Solución: vlead 50 ms (150/300 peor),
  "fresh start" único a 2.5 s, watchdog con mensaje DSP 0xe7 tipo 1 (PTS en pantalla en offset 20,
  45 kHz): si >350 ms durante 2 s → resync (máx cada 30 s); IDR se pide cuando el DSP vació la cola.
  Resultado ~190 ms, nunca >~350 ms.
- Tras error DSP: nueva sesión DSP [07f8f04].

## 4. Geometría / resolución
- 720 px = ancho máximo que saca el decoder DVD del DM642 (800 → faltan 80 col.; 800 completo
  requiere más parches DSP → ruido de líneas) [b1ecf77].
- Z4 *(PR #4)*: stream 800x480, margins w80/h120 → área AA 720x360 arriba-izq; geometría (0,0,720,360) →
  (256,0,960,480) (escala 4:3 para pantalla 1280x480).
- **Geometry hold**: tras StartVideo el servicio DVD resetea los rect a su ventana PAL (varias veces);
  el plugin reaplica cada tick (~250 ms). Fade-in: alpha 0 hasta 4 ticks estables (máx 12 / ~3 s).
- E60 LCI [a4543f8]: scaler acepta hasta ~600 px de ancho. Pantalla completa sin deformar:
  `video.txt` = `200 256 96` (área 600x224), `geom.txt` = `100 128 600 224 0 0 1280 480`.
  `video.txt` = `margin_w margin_h [dpi]` (def 160 160 140). `driver.txt` = `right` para RHD.

## 5. Firmwares HmiMain soportados (perfiles)
- 9283417A (C1A, E9x) – direcciones base del código.
- Rev 58135 `B1107-501-1121A Build 11` (E60, CI63F1 9273157A / ZB 9273159): text −0x120..−0xfe4 por
  región, data/vtables −0x116c [3e34983].
- Rev 76617 `CIC_L6_1107 B1107-501-1123S Build 46` (F30): text +0xa0/+0xbc/+0x3fc/+0x408 por región,
  data/vtables +0x7dc; 54 direcciones, 2 SigFix [ef34a1b, d210413].
- Firmware desconocido → no toca nada ("HmiMain distinto").
- **Cómo sacar HmiMain**: no es fichero en el CIC; está en la 2ª boot image
  (`memifs2 -o 0x00740000` en `/etc/starter.cfg`). Copia raw solo lectura: `cp /dev/fs0 /fs/usb0/fs0.img`
  (NUNCA escribir en /dev/fs0*). Luego `tools/hmi_profile.py --extract fs0.img HmiMain` y
  `tools/hmi_profile.py HmiMain --name ...` (47 fingerprints, comprueba vtables por nombre de tipo C++).
- HmiMain alternativos corren desde `/mnt/hbuser` (`-ro=/mnt/hbuser/f30/ro`) y solo leen manifests de
  su `ro/Plugins` → instalador también copia ahí [85c39d2].

## 6. Audio / sesión *(PR #4)*
- Por defecto **BT Audio**: no se anuncia canal media ch4 → música por A2DP; conexión C4 se libera
  tras mostrar vídeo. AA Audio usa 0xC4 (audio IBA) fuera de la gestión de fuentes, ventana de
  volumen estrecha; no hay otra etiqueta de conexión para audio DSP sin disco [bafabeb].
- Sin sensor NIGHT_DATA (forzaba "día"); espera teléfono 30 s (no 120) [c7706d3].
- Pérdida de foco (MENU, PDC, OPTION) → vídeo se reanuda solo; `live_video_ready()` solo espera SPS/PPS;
  IDR de cicaalive respondido en `input_drain()` (<100 ms) [c922f44].

## 7. Micrófono, voz de AA y tecla de voz (E9x LCI, software C16A)
Nada de este apartado está implementado en el código de este repo. Son datos de un E9x LCI con
software C16A, probados en el coche con un módulo aparte cargado en HmiMain (compilado fuera de
este repo con GCC para SH4). Las direcciones marcadas *C16A* son de ese HmiMain
(`B1103-500-1048A Build 43`); las demás son las de 9283417A que ya usa el plugin.

### Dispositivos io-audio
- Captura 0 `FACBMIC` (`/dev/snd/FACBMIC`): micrófono del coche, 4 voces; la voz está en la **voz 2**
  (config. del reconocimiento de voz BMW: `Inp_1 = PAL,FACBMIC,2,…`). Sin una conexión de audio de voz
  activa solo entrega ceros.
- Reproducción 1 `FABSDS`: salida de los avisos del diálogo de voz BMW (`AmxPrompting_1`).

### Conexión de audio 0x31
- La misma llamada con la que el plugin pide `0xC4` (`0x08b9d308` sobre `cm+0x6c8`; liberar:
  `0x08b9d460` sobre `cm+0x760`) con id **`0x31`** conecta el micrófono a FACBMIC y hace audible
  FABSDS. Es la conexión que pide el control por voz BMW (`CSpeechActivationFilter::onISpeechDialogStatus`,
  junto con `0x2C`, que no se investigó).
- `0x31` desplaza a `0xC4`: la música calla, igual que con el control por voz BMW.
- Pedida justo después de `0xC4` al arrancar la imagen → `0xC4` rechazada y no hay imagen. Hay que
  pedirla solo cuando el teléfono abre el micrófono.
- Al liberar `0x31`, `0xC4` **no** vuelve sola: hay que pedirla otra vez.
- Con `0x31` activa, el servicio de voz BMW (`scp`) abre FACBMIC; quien abre primero se queda con el
  audio. Solución: abrir la captura al mostrar la imagen AA y mantenerla abierta.
- Las llamadas van solo en el hilo HMI, por el executor de la ProcUnit (como los pasos IBA).
  `PluginApp::post()` desde el hilo de la sesión AA colgó el HMI.

### Micrófono: canal 7 del protocolo AA
1. Se abre el Assistant → canal 0 `VOICE_SESSION_REQUEST` (0x0011).
2. Canal 7 `0x8005` con open = 1 (campo 1) y max_unacked = 2 (campo 4) → responder `0x8006` con
   `08 00 10 00` (sesión 0, estado 0 = OK; estado 1 = rechazado).
3. Enviar cada 32 ms un `0x0000`: 8 bytes de timestamp (µs, big endian) + 1024 bytes PCM
   (16 kHz, mono, S16LE). El teléfono confirma cada paquete con `0x8004`.
4. Canal 7 `0x8005` con open = 0 → fin. La respuesta del Assistant llega por el canal 5.
- Captura usada: `snd_pcm_open(card 0, dev 0, capture)`, 16 kHz, 4 voces, S16LE, fragmento 2048;
  de cada frame solo se envía la voz 2.

### Voz de AA (canal 5): respuestas del Assistant
- Con el DSP en modo AAC, `cicaalive` solo le pasa el canal 4, así que el canal 5 nunca suena
  (issue #12, punto 2).
- Funciona reproducirla en FABSDS mientras `0x31` está activa: `snd_pcm_open(card 0, dev 1, playback)`,
  16 kHz mono S16LE, fragmento 1024, máx. 12 fragmentos, leyendo el canal 1 de `/cicaa_audio`.
- El canal 5 llega más rápido que en tiempo real y con AV start/stop por frase. Hizo falta:
  prebuffer de 0,35 s; no parar con el AV stop sino cuando todo se ha reproducido (y
  `playback_drain` antes de cerrar); mantener `0x31` unos 4 s tras cerrar el micrófono, para que la
  respuesta no espere al cambio de conexión; conservar la posición de lectura entre frases, para no
  repetir voz antigua.
- Las indicaciones de navegación usan el mismo canal; no se probaron expresamente.

### Tecla de voz del volante (PTT) → Assistant
- Proxy `CPxyControlElementsMFL::CPTTButton1` (símbolo `_ZTVN22CPxyControlElementsMFL11CPTTButton1E`);
  el handler está en símbolo + 32, la misma entrada que en las teclas skip del apartado 2.
  *C16A*: vtable `0x091cc9c8`, handler `0x08b7b4e8`.
- Aquí no sirve llamar primero al original: arrancaría el control por voz BMW. Para un mensaje de
  estado (`*(u8*)(msg+8) == 12`) se hace lo mismo que el handler, `valid(this,0)` →
  `decode(msg, this+124, 3)` → `valid(this,1)`, pero **sin** avisar a los listeners
  (`notify(this+80, this)` y `notify(this+112, this)`). Valor en `this+124`: 1 = pulsada, 0 = suelta.
  *C16A*: valid `0x08cf17c0`, notify `0x08b2e528`, decode `0x08b7ba78`.
- Cada pulsación llega a **3 instancias** del proxy: enviar la tecla solo en el primer cambio de valor.
- KEYCODE_SEARCH (84), down y up seguidos, abre el Assistant. Solo con la imagen AA visible; fuera
  de ella se llama al handler original y el control por voz BMW funciona como siempre.

### Sin solución
- Botón de volumen (pulsar): no llega a ningún proxy del HMI (24 proxies sondeados con la imagen AA
  visible), así que no sirve como play/pausa. El mute lo hace el sistema de audio sin pasar por el HMI.
- PDC: `sensors.PDCStatus` y `driving.gear` como `raDataRequestModel` se registran, pero nunca
  llegan datos; por CDS (`cdsAddPropertyChangedEventHandler`, `cdsGetPropertyAsync`) tampoco
  responde nada a un plugin local.
