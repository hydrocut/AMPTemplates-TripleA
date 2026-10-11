#!/bin/bash
# lancer-triplea.sh - pose par le template AMP TeamKit (recree a chaque Update).
# Argument : <port du jeu>   (ligne de commande d'AMP)
#
# 1. lit les reglages ecrits par AMP (reglages-triplea.txt, une ligne cle=valeur) : nom du
#    bot, commentaire du lobby, memoire de Java ; les filtre (TripleA refuse de demarrer si
#    le nom ne commence pas par « Bot » ou fait plus de 21 caracteres, ou si le commentaire
#    depasse 14 caracteres : HeadlessGameRunner.java) ;
# 2. lance le serveur de partie de TripleA (org.triplea.game.server.HeadlessGameRunner) avec
#    le Java de l'instance : -Dtriplea.name, -Dtriplea.port, -Dtriplea.lobby.uri (lobby
#    officiel, obligatoire pour ce serveur), -Dtriplea.lobby.game.comments, variable
#    MAPS_FOLDER (dossier cartes/) et user.home dans donnees/ (sauvegardes automatiques et
#    preferences de Java restent dans l'instance) ;
# 3. a l'arret demande par AMP (SIGTERM), le transmet au serveur : il enregistre la partie en
#    cours (autosave) puis s'arrete (60 s au plus, sa propre minuterie) ;
# 4. si le serveur s'arrete tout seul, explique en francais les causes connues.
#
# Aucune valeur n'est evaluee par le shell : elles sont filtrees caractere par caractere et
# passees a Java comme arguments distincts d'un tableau (jamais dans une commande construite).
cd "$(dirname "$0")" || exit 1
ICI="$PWD"
JAVA="$ICI/java/bin/java"
JAR="$ICI/triplea-serveur/bin/game-headless.jar"
REGLAGES="$ICI/reglages-triplea.txt"
CARTES="$ICI/cartes"
DONNEES="$ICI/donnees"
LOBBY="https://prod.triplea-game.org"
NOM_DEFAUT="Bot_TeamKit_FR"
COMMENTAIRE_DEFAUT="TeamKit FR"
export LANG=C.UTF-8 LC_ALL=C.UTF-8

PORT="${1:-3300}"
if ! [[ "$PORT" =~ ^[0-9]{1,5}$ ]] || [ "$((10#$PORT))" -lt 1 ] || [ "$((10#$PORT))" -gt 65535 ]; then
  echo "ERREUR : port du jeu invalide : $PORT"
  exit 1
fi
PORT=$((10#$PORT))
if [ ! -x "$JAVA" ] || [ ! -f "$JAR" ]; then
  echo "ERREUR : TripleA ou Java n'est pas installe dans ce dossier. Lance Update dans AMP."
  exit 1
fi

# ── Reglages (une ligne cle=valeur) ──────────────────────────────────────────────
# Une cle presente deux fois (retour a la ligne glisse dans un texte pour imiter une autre
# cle) : aucune des deux valeurs n'est crue, la valeur par defaut est prise.
NOM_BOT="$NOM_DEFAUT"; COMMENTAIRE="$COMMENTAIRE_DEFAUT"; MEMOIRE=512
VUS=" "; DOUBLONS=""
if [ -f "$REGLAGES" ]; then
  while IFS= read -r ligne || [ -n "$ligne" ]; do
    ligne="${ligne%$'\r'}"
    cle="${ligne%%=*}"
    [ "$cle" = "$ligne" ] && continue
    case "$cle" in nom_bot|commentaire|memoire) ;; *) continue ;; esac
    case "$VUS" in *" $cle "*) DOUBLONS="$DOUBLONS $cle"; continue ;; esac
    VUS="$VUS$cle "
    val="${ligne#*=}"
    # Variable laissee telle quelle par AMP (instance creee avant ce reglage) : defaut.
    [[ "$val" =~ ^[{][{][a-z_]+[}][}]$ ]] && continue
    case "$cle" in
      nom_bot) NOM_BOT="$val" ;;
      commentaire) COMMENTAIRE="$val" ;;
      memoire) MEMOIRE="$val" ;;
    esac
  done < "$REGLAGES"
  for cle in $DOUBLONS; do
    echo "TeamKit : $cle apparait plusieurs fois dans les reglages (retour a la ligne dans un texte ?) : valeur par defaut."
    case "$cle" in
      nom_bot) NOM_BOT="$NOM_DEFAUT" ;;
      commentaire) COMMENTAIRE="$COMMENTAIRE_DEFAUT" ;;
      memoire) MEMOIRE=512 ;;
    esac
  done
else
  echo "TeamKit : $(basename "$REGLAGES") absent (AMP l'ecrit au demarrage), reglages par defaut."
fi

# Accents courants -> lettres simples, puis seulement l'ASCII voulu.
sans_accents() {
  printf '%s' "$1" | tr -d '\000-\037\177' \
    | sed 'y/àâäáãåéèêëíìîïóòôöõúùûüýÿçñÀÂÄÁÃÅÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÝÇÑ/aaaaaaeeeeiiiiooooouuuuyycnAAAAAAEEEEIIIIOOOOOUUUUYCN/' \
    | sed -e 's/œ/oe/g' -e 's/Œ/OE/g' -e 's/æ/ae/g' -e 's/Æ/AE/g' -e 's/ß/ss/g'
}

# Nom du bot : TripleA exige « Bot » au debut et 7 a 21 caracteres (sinon il s'arrete).
AVANT="$NOM_BOT"
NOM=$(sans_accents "$NOM_BOT" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/[[:space:]]\{1,\}/_/g' | LC_ALL=C tr -cd 'A-Za-z0-9_-')
if [ -z "$NOM" ]; then
  NOM="$NOM_DEFAUT"
elif [[ "${NOM,,}" == bot* ]]; then
  NOM="Bot${NOM:3}"
else
  NOM="Bot_$NOM"
fi
NOM="${NOM:0:21}"
if [ "${#NOM}" -lt 7 ]; then
  echo "TeamKit : nom du bot « $NOM » trop court (7 caracteres au moins) : « $NOM_DEFAUT » utilise."
  NOM="$NOM_DEFAUT"
elif [ "$NOM" != "$AVANT" ]; then
  echo "TeamKit : nom du bot adapte aux regles de TripleA (Bot au debut, 21 caracteres au plus, lettres sans accent, chiffres, _ et -) : « $NOM »."
fi

# Commentaire du lobby : 14 caracteres au plus (au-dela TripleA s'arrete).
AVANT="$COMMENTAIRE"
COMMENTAIRE=$(sans_accents "$COMMENTAIRE" | LC_ALL=C tr -cd '\040-\176' | sed -e 's/^ *//' -e 's/ *$//' -e 's/  */ /g')
if [ "${#COMMENTAIRE}" -gt 14 ]; then
  COMMENTAIRE=$(printf '%s' "${COMMENTAIRE:0:14}" | sed 's/ *$//')
  echo "TeamKit : commentaire du lobby coupe a 14 caracteres (limite de TripleA) : « $COMMENTAIRE »."
elif [ "$COMMENTAIRE" != "$AVANT" ]; then
  echo "TeamKit : commentaire du lobby adapte (lettres sans accent et ponctuation simple) : « $COMMENTAIRE »."
fi

case "$MEMOIRE" in
  256|512|1024|2048) ;;
  *) echo "TeamKit : memoire « $MEMOIRE » inconnue, 512 Mo."; MEMOIRE=512 ;;
esac

# ── Dossiers, cartes ─────────────────────────────────────────────────────────────
mkdir -p "$CARTES" "$DONNEES" || exit 1
shopt -s nullglob
A_EXTRAIRE=("$CARTES"/*.zip)
INSTALLEES=0
# Le serveur extrait cartes/<nom>.zip dans cartes/<nom>/<nom>-master/ (map.yml dedans).
for d in "$CARTES"/*/; do
  TROUVES=("$d"*/map.yml)
  { [ -f "$d"map.yml ] || [ "${#TROUVES[@]}" -gt 0 ]; } && INSTALLEES=$((INSTALLEES + 1))
done
shopt -u nullglob
if [ "$INSTALLEES" -eq 0 ] && [ "${#A_EXTRAIRE[@]}" -eq 0 ]; then
  echo "TeamKit : ATTENTION, aucune carte dans le dossier cartes : les joueurs ne pourront rien lancer. Renseigne Cartes a installer puis fais un Update."
else
  echo "TeamKit : $INSTALLEES carte(s) installee(s)${A_EXTRAIRE:+, ${#A_EXTRAIRE[@]} a extraire maintenant}."
fi

VERSION=$(cat "$ICI/triplea-serveur/.version" 2>/dev/null)
echo "TeamKit : TripleA ${VERSION:-?} (Java $(cat "$ICI/java/.version-temurin" 2>/dev/null || echo '?')), bot « $NOM », port $PORT/TCP, lobby $LOBBY, ${MEMOIRE} Mo."
echo "TeamKit : le lobby va verifier que le port $PORT est joignable depuis internet ; sinon le serveur s'arrete."

# Variables que TripleA lit si une propriete manque : on ne laisse passer que les notres.
unset BOT_NAME BOT_PORT BOT_COMMENT BOT_LOBBY_URI
export MAPS_FOLDER="$CARTES"
ARGS=(
  "-Xmx${MEMOIRE}m"
  "-Xss1250k"
  "-Djava.awt.headless=true"
  "-Djava.net.preferIPv4Stack=true"
  "-Duser.home=$DONNEES"
  # Preferences « systeme » de Java dans l'instance : sinon, sans droit d'ecriture sur
  # /etc/.java, Java previent toutes les 30 s qu'il ne peut pas les verrouiller.
  "-Djava.util.prefs.systemRoot=$DONNEES/.java-systeme"
  "-Dlogback.statusListenerClass=ch.qos.logback.core.status.NopStatusListener"
  "-Dtriplea.name=$NOM"
  "-Dtriplea.port=$PORT"
  "-Dtriplea.lobby.uri=$LOBBY"
  "-Dtriplea.lobby.game.comments=$COMMENTAIRE"
  "-Dtriplea.exit.on.game.end=false"
  "-jar" "$JAR"
)
# --pdeathsig : si ce script est tue net (SIGKILL), Java recoit SIGTERM et s'arrete aussi.
if command -v setpriv >/dev/null 2>&1; then
  setpriv --pdeathsig TERM -- "$JAVA" "${ARGS[@]}" </dev/null &
else
  "$JAVA" "${ARGS[@]}" </dev/null &
fi
PID=$!

ARRET=0
arreter() {
  trap - TERM INT
  ARRET=1
  echo "TeamKit : arret demande, le serveur enregistre la partie en cours puis s'arrete (60 s au plus)."
  kill -TERM "$PID" 2>/dev/null
}
trap arreter TERM INT

# Le SIGTERM d'AMP interrompt ce « wait » : on attend une seconde fois le vrai code.
wait "$PID"
CODE=$?
if [ "$ARRET" = 1 ]; then
  wait "$PID" 2>/dev/null
  C2=$?
  [ "$C2" != 127 ] && CODE=$C2
fi
if [ "$ARRET" = 1 ]; then
  if [ "$CODE" = 0 ] || [ "$CODE" = 143 ]; then
    echo "TeamKit : serveur arrete."
    exit 0
  fi
  echo "TeamKit : serveur arrete (code $CODE)."
  exit "$CODE"
fi
if [ "$CODE" = 0 ]; then
  echo "TeamKit : le serveur s'est arrete de lui-meme (code 0) : un moderateur du lobby de TripleA peut arreter un bot a distance. Redemarre l'instance."
else
  echo "TeamKit : le serveur s'est arrete tout seul (code $CODE). Causes connues, voir les lignes au-dessus :"
  echo "TeamKit :  - « Your computer is not reachable from the internet » : le lobby n'a pas pu joindre le port $PORT/TCP (pare-feu, port non publie par le conteneur) ;"
  echo "TeamKit :  - « Failed to run game server » ou « Connection refused » : lobby $LOBBY injoignable ;"
  echo "TeamKit :  - « UnsupportedClassVersionError » : Java trop ancien, refais un Update ;"
  echo "TeamKit :  - « Could not open network port » : le port $PORT est deja pris."
fi
exit "$CODE"
