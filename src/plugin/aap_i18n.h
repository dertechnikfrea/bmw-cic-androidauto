#ifndef AAP_I18N_H
#define AAP_I18N_H
/* UI localisation from the CIC's own language setting.
 *
 * Source of truth: the HMI's CPxyManMachineInterface proxy (instance 1,
 * HmiMain 9283417A / C1A), property CurrentLanguage at +0x750, read with the
 * same getter CIbaCommunication::onStatusCurrentLanguage uses (0x08bea500:
 * returns 1 when the property is valid and copies the ELanguage value).
 * ELanguage values were recovered from the IBA language-code switch
 * (CIbaLanguageCode, 0x082bc844): 1 de-de, 2 en-gb, 3 en-us, 4 es, 5 it,
 * 6 fr, 7/8 nl, 9 ar, 10 zh-tw, 11 zh-cn, 12 ko, 13 ja, 14 ru, 15 fr(CA),
 * 16 es(MX), 17 pt, 18 pl, 19 el, 20 tr, 21 hu, 22 ro, 23 sv.
 *
 * Native calls only on the HMI thread and only after the HmiMain signature
 * check passed. Anything unknown -> English. The Spanish texts already in the
 * code are the keys, so internal str_eq() comparisons keep working: only the
 * text sent to the HMI models is translated. Texts stay ASCII (no accents or
 * umlauts) like the original Spanish ones, the CIC font path is not verified
 * for UTF-8. */

enum AapLang { AAP_ES = 0, AAP_EN, AAP_DE, AAP_FR, AAP_IT, AAP_NL, AAP_PT, AAP_LANGS };

/* .bss (no static ctors on the CIC): 0 = not detected yet. */
static volatile int g_lang_set;
static volatile int g_lang;        /* AapLang */
static int g_lang_raw;             /* ELanguage as read, for the log */

static int aap_lang_from_cic(int e) {
    switch (e) {
    case 1: return AAP_DE;
    case 4: case 16: return AAP_ES;
    case 5: return AAP_IT;
    case 6: case 15: return AAP_FR;
    case 7: case 8: return AAP_NL;
    case 17: return AAP_PT;
    default: return AAP_EN;     /* 2/3 English and every language without texts */
    }
}

/* proxy +0x750 holds a CCurrentLanguage property object; accept the vptrs of
 * its class and of the two simple-property templates it derives from. */
static int aap_lang_vptr_ok(unsigned long v) {
    return v == 0x09213980UL || v == 0x09231840UL || v == 0x09231814UL;
}

/* HMI thread only. Returns 1 when the language was read from the CIC. */
static int aap_lang_read(int* out) {
    typedef void* (*MmiFactory)(unsigned);
    typedef int (*GetLanguage)(void*, int*);
    void* mmi = ((MmiFactory)0x08be9fb0UL)(1);
    if (!mmi) return 0;
    void* prop = (char*)mmi + 0x750;
    if (!aap_lang_vptr_ok(*(unsigned long*)prop)) return 0;
    int v = 0;
    if (!((GetLanguage)0x08bea500UL)(prop, &v)) return 0;
    *out = v;
    return 1;
}

struct AapText { const char* t[AAP_LANGS]; };   /* es, en, de, fr, it, nl, pt */
static const AapText kAapTexts[] = {
 /* plugin: connect / status */
 {{"Volviendo a Android Auto...", "Returning to Android Auto...", "Zurueck zu Android Auto...", "Retour a Android Auto...", "Ritorno ad Android Auto...", "Terug naar Android Auto...", "A voltar ao Android Auto..."}},
 {{"Cerrando video anterior, espera unos segundos", "Closing previous video, wait a few seconds", "Vorheriges Video wird beendet, bitte warten", "Fermeture de la video precedente, patientez", "Chiusura video precedente, attendi qualche secondo", "Vorige video wordt gesloten, even geduld", "A fechar o video anterior, aguarde"}},
 {{"Falta libcicaa.so (instalar)", "libcicaa.so missing (install)", "libcicaa.so fehlt (installieren)", "libcicaa.so manquant (installer)", "Manca libcicaa.so (installare)", "libcicaa.so ontbreekt (installeren)", "Falta libcicaa.so (instalar)"}},
 {{"No se pudo cargar libcicaa.so", "Could not load libcicaa.so", "libcicaa.so konnte nicht geladen werden", "Impossible de charger libcicaa.so", "Impossibile caricare libcicaa.so", "Kan libcicaa.so niet laden", "Nao foi possivel carregar libcicaa.so"}},
 {{"libcicaa.so incompatible", "libcicaa.so incompatible", "libcicaa.so inkompatibel", "libcicaa.so incompatible", "libcicaa.so incompatibile", "libcicaa.so niet compatibel", "libcicaa.so incompativel"}},
 {{"Ya en marcha", "Already running", "Laeuft bereits", "Deja en cours", "Gia in esecuzione", "Draait al", "Ja em execucao"}},
 {{"Error arrancando AA", "Error starting AA", "Fehler beim Starten von AA", "Erreur au demarrage d'AA", "Errore avvio AA", "Fout bij starten AA", "Erro ao iniciar AA"}},
 {{"Error creando hilo", "Error creating thread", "Fehler beim Erstellen des Threads", "Erreur de creation du thread", "Errore creazione thread", "Fout bij maken thread", "Erro ao criar thread"}},
 {{"Conecta el movil por USB...", "Connect the phone via USB...", "Telefon per USB verbinden...", "Branchez le telephone en USB...", "Collega il telefono via USB...", "Sluit de telefoon aan via USB...", "Ligue o telemovel por USB..."}},
 {{"No se pudo cargar el DSP parcheado (reinstalar)", "Could not load patched DSP (reinstall)", "Gepatchter DSP nicht ladbar (neu installieren)", "Impossible de charger le DSP modifie (reinstaller)", "Impossibile caricare il DSP modificato (reinstallare)", "Gepatchte DSP niet geladen (opnieuw installeren)", "Nao foi possivel carregar o DSP (reinstalar)"}},
 /* IBA / native video */
 {{"Hilo HMI distinto", "Different HMI thread", "Anderer HMI-Thread", "Thread HMI different", "Thread HMI diverso", "Andere HMI-thread", "Thread HMI diferente"}},
 {{"HmiMain distinto: no compatible", "Different HmiMain: not compatible", "Anderes HmiMain: nicht kompatibel", "HmiMain different : incompatible", "HmiMain diverso: non compatibile", "Andere HmiMain: niet compatibel", "HmiMain diferente: incompativel"}},
 {{"Faltan servicios de video del CIC", "CIC video services missing", "CIC-Videodienste fehlen", "Services video du CIC absents", "Servizi video del CIC mancanti", "CIC-videodiensten ontbreken", "Faltam servicos de video do CIC"}},
 {{"Layout de servicios distinto", "Different service layout", "Andere Dienststruktur", "Structure des services differente", "Struttura servizi diversa", "Andere dienstindeling", "Estrutura de servicos diferente"}},
 {{"No se pudo registrar listener", "Could not register listener", "Listener konnte nicht registriert werden", "Impossible d'enregistrer l'ecouteur", "Impossibile registrare il listener", "Kan listener niet registreren", "Nao foi possivel registar o listener"}},
 {{"Suscripcion de propiedades fallo", "Property subscription failed", "Eigenschaftsabo fehlgeschlagen", "Echec de l'abonnement aux proprietes", "Sottoscrizione proprieta fallita", "Abonnement op eigenschappen mislukt", "Subscricao de propriedades falhou"}},
 {{"Pantalla de video ocupada por otra fuente", "Video screen busy with another source", "Videobild von anderer Quelle belegt", "Ecran video occupe par une autre source", "Schermo video occupato da un'altra sorgente", "Videoscherm bezet door andere bron", "Ecra de video ocupado por outra fonte"}},
 {{"Tabla de video distinta", "Different video table", "Andere Videotabelle", "Table video differente", "Tabella video diversa", "Andere videotabel", "Tabela de video diferente"}},
 {{"Esperando ruta de video", "Waiting for video route", "Warte auf Videopfad", "Attente du chemin video", "In attesa del percorso video", "Wachten op videoroute", "A aguardar rota de video"}},
 {{"Ruta de video cambiada por otro cliente", "Video route changed by another client", "Videopfad von anderem Client geaendert", "Chemin video modifie par un autre client", "Percorso video cambiato da un altro client", "Videoroute gewijzigd door andere client", "Rota de video alterada por outro cliente"}},
 {{"Fallo restaurando video; reinicia el CIC", "Video restore failed; restart the CIC", "Video-Wiederherstellung fehlgeschlagen; CIC neu starten", "Echec de restauration video ; redemarrez le CIC", "Ripristino video fallito; riavvia il CIC", "Video herstellen mislukt; herstart de CIC", "Falha ao restaurar video; reinicie o CIC"}},
 {{"No se pudo arrancar cicaalive", "Could not start cicaalive", "cicaalive konnte nicht gestartet werden", "Impossible de demarrer cicaalive", "Impossibile avviare cicaalive", "Kan cicaalive niet starten", "Nao foi possivel iniciar cicaalive"}},
 {{"cicaalive termino antes de mostrar video", "cicaalive ended before showing video", "cicaalive vor Videoanzeige beendet", "cicaalive s'est arrete avant la video", "cicaalive terminato prima del video", "cicaalive gestopt voor video zichtbaar was", "cicaalive terminou antes do video"}},
 {{"Accion fuera del hilo HMI", "Action outside HMI thread", "Aktion ausserhalb des HMI-Threads", "Action hors du thread HMI", "Azione fuori dal thread HMI", "Actie buiten HMI-thread", "Acao fora do thread HMI"}},
 {{"Callback fuera del hilo HMI", "Callback outside HMI thread", "Callback ausserhalb des HMI-Threads", "Callback hors du thread HMI", "Callback fuori dal thread HMI", "Callback buiten HMI-thread", "Callback fora do thread HMI"}},
 {{"Falta cicaalive (reinstalar)", "cicaalive missing (reinstall)", "cicaalive fehlt (neu installieren)", "cicaalive manquant (reinstaller)", "Manca cicaalive (reinstallare)", "cicaalive ontbreekt (opnieuw installeren)", "Falta cicaalive (reinstalar)"}},
 {{"Capa de video ocupada por otro cliente", "Video layer busy with another client", "Videoebene von anderem Client belegt", "Couche video occupee par un autre client", "Livello video occupato da un altro client", "Videolaag bezet door andere client", "Camada de video ocupada por outro cliente"}},
 {{"Hilo HMI no verificado", "HMI thread not verified", "HMI-Thread nicht verifiziert", "Thread HMI non verifie", "Thread HMI non verificato", "HMI-thread niet geverifieerd", "Thread HMI nao verificado"}},
 {{"Hilo del CIC no verificado.", "CIC thread not verified.", "CIC-Thread nicht verifiziert.", "Thread du CIC non verifie.", "Thread del CIC non verificato.", "CIC-thread niet geverifieerd.", "Thread do CIC nao verificado."}},
 {{"Falta cicaalive instalado.", "cicaalive is not installed.", "cicaalive ist nicht installiert.", "cicaalive n'est pas installe.", "cicaalive non installato.", "cicaalive is niet geinstalleerd.", "cicaalive nao esta instalado."}},
 {{"No se pudo completar la operacion.", "The operation could not be completed.", "Vorgang konnte nicht abgeschlossen werden.", "L'operation n'a pas pu aboutir.", "Impossibile completare l'operazione.", "De bewerking kon niet worden voltooid.", "Nao foi possivel concluir a operacao."}},
 {{"El CIC no responde; reinicia el CIC.", "The CIC is not responding; restart the CIC.", "CIC reagiert nicht; CIC neu starten.", "Le CIC ne repond pas ; redemarrez-le.", "Il CIC non risponde; riavvia il CIC.", "De CIC reageert niet; herstart de CIC.", "O CIC nao responde; reinicie o CIC."}},
 {{"El CIC no responde.", "The CIC is not responding.", "CIC reagiert nicht.", "Le CIC ne repond pas.", "Il CIC non risponde.", "De CIC reageert niet.", "O CIC nao responde."}},
 {{"No se puede comunicar con el CIC.", "Cannot communicate with the CIC.", "Keine Kommunikation mit dem CIC.", "Communication impossible avec le CIC.", "Impossibile comunicare con il CIC.", "Kan niet communiceren met de CIC.", "Nao e possivel comunicar com o CIC."}},
 /* auto_player.h */
 {{"Reproductor desconocido.", "Unknown player.", "Unbekannter Player.", "Lecteur inconnu.", "Lettore sconosciuto.", "Onbekende speler.", "Leitor desconhecido."}},
 {{"Hay una sesion activa o un cierre pendiente. Pulsa Detener.", "A session is active or closing. Press Stop.", "Sitzung aktiv oder wird beendet. Stopp druecken.", "Session active ou fermeture en cours. Appuyez sur Arreter.", "Sessione attiva o in chiusura. Premi Stop.", "Sessie actief of wordt gesloten. Druk op Stop.", "Sessao ativa ou a fechar. Prima Parar."}},
 {{"No se puede preparar otra sesion: cierre pendiente.", "Cannot prepare another session: closing pending.", "Keine neue Sitzung: Beenden ausstehend.", "Nouvelle session impossible : fermeture en attente.", "Impossibile preparare un'altra sessione: chiusura in corso.", "Geen nieuwe sessie mogelijk: sluiten bezig.", "Nao e possivel preparar outra sessao: fecho pendente."}},
 {{"Preparando reproductor...", "Preparing player...", "Player wird vorbereitet...", "Preparation du lecteur...", "Preparazione lettore...", "Speler voorbereiden...", "A preparar o leitor..."}},
 {{"Deteniendo y liberando recursos...", "Stopping and releasing resources...", "Stoppe und gebe Ressourcen frei...", "Arret et liberation des ressources...", "Arresto e rilascio risorse...", "Stoppen en bronnen vrijgeven...", "A parar e a libertar recursos..."}},
 {{"Error; recursos liberados.", "Error; resources released.", "Fehler; Ressourcen freigegeben.", "Erreur ; ressources liberees.", "Errore; risorse rilasciate.", "Fout; bronnen vrijgegeven.", "Erro; recursos libertados."}},
 {{"Detenido.", "Stopped.", "Gestoppt.", "Arrete.", "Fermato.", "Gestopt.", "Parado."}},
 {{"Cierre sin confirmar. Recursos retenidos; Detener permite reintentarlo.", "Close not confirmed. Resources held; Stop retries it.", "Beenden unbestaetigt. Ressourcen gehalten; Stopp wiederholt.", "Fermeture non confirmee. Ressources retenues ; Arreter reessaie.", "Chiusura non confermata. Risorse trattenute; Stop riprova.", "Sluiten niet bevestigd. Bronnen vastgehouden; Stop probeert opnieuw.", "Fecho nao confirmado. Recursos retidos; Parar tenta de novo."}},
 {{"El CIC rechazo el cierre. Recursos retenidos; revisar diagnostico.", "The CIC rejected the close. Resources held; check diagnostics.", "CIC hat Beenden abgelehnt. Ressourcen gehalten; Diagnose pruefen.", "Le CIC a refuse la fermeture. Ressources retenues ; voir diagnostic.", "Il CIC ha rifiutato la chiusura. Risorse trattenute; vedi diagnostica.", "De CIC weigerde het sluiten. Bronnen vastgehouden; controleer diagnose.", "O CIC recusou o fecho. Recursos retidos; ver diagnostico."}},
 {{"Tiempo agotado esperando confirmacion del CIC.", "Timed out waiting for CIC confirmation.", "Zeitueberschreitung beim Warten auf CIC.", "Delai depasse en attendant le CIC.", "Tempo scaduto in attesa del CIC.", "Time-out bij wachten op CIC.", "Tempo esgotado a aguardar o CIC."}},
 {{"El reproductor termino con error; consulta el diagnostico.", "The player ended with an error; see diagnostics.", "Player mit Fehler beendet; Diagnose pruefen.", "Le lecteur s'est arrete sur une erreur ; voir diagnostic.", "Il lettore e terminato con errore; vedi diagnostica.", "De speler stopte met een fout; zie diagnose.", "O leitor terminou com erro; ver diagnostico."}},
 {{"Tiempo agotado preparando el video; cerrando sesion.", "Timed out preparing video; closing session.", "Zeitueberschreitung bei Videostart; Sitzung wird beendet.", "Delai depasse pour la video ; fermeture de la session.", "Tempo scaduto preparando il video; chiusura sessione.", "Time-out bij voorbereiden video; sessie wordt gesloten.", "Tempo esgotado a preparar o video; a fechar sessao."}},
 {{"Reproductor iniciado.", "Player started.", "Player gestartet.", "Lecteur demarre.", "Lettore avviato.", "Speler gestart.", "Leitor iniciado."}},
 {{"Conectando audio...", "Connecting audio...", "Audio wird verbunden...", "Connexion audio...", "Connessione audio...", "Audio verbinden...", "A ligar o audio..."}},
 {{"Abriendo video...", "Opening video...", "Video wird geoeffnet...", "Ouverture de la video...", "Apertura video...", "Video openen...", "A abrir o video..."}},
 {{"Conectando pantalla...", "Connecting display...", "Anzeige wird verbunden...", "Connexion de l'ecran...", "Connessione schermo...", "Scherm verbinden...", "A ligar o ecra..."}},
 {{"Arrancando video...", "Starting video...", "Video wird gestartet...", "Demarrage de la video...", "Avvio video...", "Video starten...", "A iniciar o video..."}},
 {{"Preparando imagen...", "Preparing picture...", "Bild wird vorbereitet...", "Preparation de l'image...", "Preparazione immagine...", "Beeld voorbereiden...", "A preparar a imagem..."}},
 {{"Esperando respuesta del CIC...", "Waiting for CIC reply...", "Warte auf CIC-Antwort...", "Attente de reponse du CIC...", "In attesa di risposta dal CIC...", "Wachten op antwoord CIC...", "A aguardar resposta do CIC..."}},
 /* libcicaa.so status / result */
 {{"sin iniciar", "not started", "nicht gestartet", "non demarre", "non avviato", "niet gestart", "nao iniciado"}},
 {{"arrancando...", "starting...", "startet...", "demarrage...", "avvio...", "starten...", "a iniciar..."}},
 {{"error creando hilo", "error creating thread", "Fehler beim Erstellen des Threads", "erreur de creation du thread", "errore creazione thread", "fout bij maken thread", "erro ao criar thread"}},
 {{"Falta certificado AA", "AA certificate missing", "AA-Zertifikat fehlt", "Certificat AA manquant", "Certificato AA mancante", "AA-certificaat ontbreekt", "Falta certificado AA"}},
 {{"falta hu.crt/hu.key (AAHU.CRT/AAHU.KEY en el USB al instalar)", "hu.crt/hu.key missing (AAHU.CRT/AAHU.KEY on the USB stick when installing)", "hu.crt/hu.key fehlt (AAHU.CRT/AAHU.KEY bei Installation auf USB)", "hu.crt/hu.key manquant (AAHU.CRT/AAHU.KEY sur la cle USB a l'installation)", "manca hu.crt/hu.key (AAHU.CRT/AAHU.KEY sulla chiavetta all'installazione)", "hu.crt/hu.key ontbreekt (AAHU.CRT/AAHU.KEY op USB bij installatie)", "falta hu.crt/hu.key (AAHU.CRT/AAHU.KEY na pen ao instalar)"}},
 {{"Esperando movil por USB...", "Waiting for phone on USB...", "Warte auf Telefon an USB...", "Attente du telephone en USB...", "In attesa del telefono via USB...", "Wachten op telefoon via USB...", "A aguardar telemovel por USB..."}},
 {{"Sin movil", "No phone", "Kein Telefon", "Pas de telephone", "Nessun telefono", "Geen telefoon", "Sem telemovel"}},
 {{"no se detecto movil Android Auto", "no Android Auto phone detected", "kein Android-Auto-Telefon erkannt", "aucun telephone Android Auto detecte", "nessun telefono Android Auto rilevato", "geen Android Auto-telefoon gevonden", "nenhum telemovel Android Auto detetado"}},
 {{"Sesion terminada", "Session ended", "Sitzung beendet", "Session terminee", "Sessione terminata", "Sessie beeindigd", "Sessao terminada"}},
 {{"Sesion terminada con error", "Session ended with error", "Sitzung mit Fehler beendet", "Session terminee avec erreur", "Sessione terminata con errore", "Sessie beeindigd met fout", "Sessao terminada com erro"}},
 {{"AA: sesion activa", "AA: session active", "AA: Sitzung aktiv", "AA : session active", "AA: sessione attiva", "AA: sessie actief", "AA: sessao ativa"}},
 {{"AA: accesorio AOA detectado", "AA: AOA accessory detected", "AA: AOA-Zubehoer erkannt", "AA : accessoire AOA detecte", "AA: accessorio AOA rilevato", "AA: AOA-accessoire gevonden", "AA: acessorio AOA detetado"}},
 {{"AA: movil detectado, cambiando a AOA", "AA: phone detected, switching to AOA", "AA: Telefon erkannt, wechsle zu AOA", "AA : telephone detecte, passage en AOA", "AA: telefono rilevato, passaggio ad AOA", "AA: telefoon gevonden, overschakelen naar AOA", "AA: telemovel detetado, a mudar para AOA"}},
};

static int aap_streq(const char* a, const char* b) {
    while (*a && *a == *b) { ++a; ++b; }
    return *a == *b;
}

/* Spanish key -> current language. Unknown text is returned unchanged. */
static const char* tr(const char* es) {
    int l = g_lang_set ? g_lang : AAP_ES;
    if (!es || l == AAP_ES) return es;
    for (unsigned i = 0; i < sizeof kAapTexts / sizeof kAapTexts[0]; ++i)
        if (aap_streq(kAapTexts[i].t[AAP_ES], es)) return kAapTexts[i].t[l];
    return es;
}

/* "etapa N/7: ..." (libcicaa result) -> localised prefix + same tail. */
static const char* const kAapStage[AAP_LANGS] = {"etapa ", "stage ", "Stufe ", "etape ", "fase ", "fase ", "etapa "};
static const char* tr_stage(const char* s, char* buf, unsigned cap) {
    const char* k = "etapa ";
    unsigned i = 0;
    while (k[i] && s[i] == k[i]) ++i;
    if (k[i]) return tr(s);
    int l = g_lang_set ? g_lang : AAP_ES;
    unsigned n = 0;
    for (const char* p = kAapStage[l]; *p && n + 1 < cap; ++p) buf[n++] = *p;
    for (const char* p = s + i; *p && n + 1 < cap; ++p) buf[n++] = *p;
    buf[n] = 0;
    return buf;
}
#endif
