#!/bin/bash
# installer-triplea.sh - pose par le template AMP TeamKit (recree a chaque Update).
# Arguments : <dossier de l'instance (FullBaseDir cote AMP)> [version] [cartes] [maj_cartes]
#
# Trois etapes, chacune sautee si deja a jour :
#  1. le serveur de partie (headless) de TripleA : game-headless.zip de la release GitHub
#     demandee (vide = la derniere publiee, releases/latest), dans triplea-serveur/ ;
#  2. Java : le serveur exige la version de Java de ses classes (Java 25 pour les versions
#     d'octobre 2026) ; on prend le JRE Eclipse Temurin de cette version sur api.adoptium.net
#     (empreinte SHA-256 verifiee), dans java/, comme le template Mindustry de CubeCoders ;
#  3. les cartes demandees : adresse et date de derniere modification lues dans le catalogue
#     officiel (https://prod.triplea-game.org/support/maps/listing, celui qu'utilisent les bots
#     officiels), zip depose dans cartes/ : le serveur l'extrait lui-meme au demarrage
#     (ZippedMapsExtractor) et efface le zip.
#
# Licence : TripleA est sous GPL-3.0 ; le depot du template ne contient aucun binaire, tout
# est telecharge ici depuis les sources officielles. Les donnees (donnees/, cartes deja
# installees) ne sont jamais effacees.
#
# Les valeurs des reglages ne sont jamais executees : elles sont comparees, filtrees par des
# expressions regulieres, et ne passent a perl que comme arguments.
set -u
cd "$1" 2>/dev/null || { echo "ERREUR : dossier de l'instance introuvable : ${1:-}"; exit 1; }
ICI="$PWD"
VERSION_ARG="${2-__absent__}"
CARTES_ARG="${3-__absent__}"
MAJ_ARG="${4-__absent__}"
REGLAGES="$ICI/reglages-triplea.txt"
DEPOT=triplea-game/triplea
SERVEUR="$ICI/triplea-serveur"
JAR="$SERVEUR/bin/game-headless.jar"
JAVA_DIR="$ICI/java"
CARTES="$ICI/cartes"
TEMP="$ICI/.telechargement"
MARQUE_CARTES="$ICI/.cartes-installees"
CATALOGUE="https://prod.triplea-game.org/support/maps/listing"
CARTES_DEFAUT="world_war_ii_classic, world_war_ii_revised, world_war_ii_v3, world_war_ii_global"
export LANG=C.UTF-8 LC_ALL=C.UTF-8

for outil in curl unzip perl sha256sum tar od head sed; do
  if ! command -v "$outil" >/dev/null 2>&1; then
    echo "ERREUR : l'outil $outil manque. Cette instance doit tourner en conteneur : curl, unzip et perl sont installes par ExtraContainerPackages."
    exit 1
  fi
done
if ! perl -MJSON::PP -e 1 >/dev/null 2>&1; then
  echo "ERREUR : le module perl JSON::PP manque (paquet perl complet). Il est installe par ExtraContainerPackages : recree le conteneur de l'instance."
  exit 1
fi

# Valeur d'un reglage : celle passee par AMP sur la ligne de commande de l'Update ; si AMP
# ne l'a pas remplacee (variable laissee telle quelle) ou ne l'a pas passee, celle du
# dernier demarrage (reglages-triplea.txt), sinon la valeur par defaut.
non_remplacee() { [ "$1" = __absent__ ] || [[ "$1" =~ ^[{][{].*[}][}]$ ]]; }
du_fichier() {
  local v
  [ -f "$REGLAGES" ] || return 1
  v=$(sed -n "s/^$1=//p" "$REGLAGES" | head -n 1 | tr -d '\r')
  grep -q "^$1=" "$REGLAGES" || return 1
  non_remplacee "$v" && return 1
  printf '%s' "$v"
}
reglage() {   # <cle> <valeur passee> <defaut>
  local v="$2"
  if non_remplacee "$v"; then
    if v=$(du_fichier "$1"); then
      echo "TeamKit : $1 lu dans les reglages du dernier demarrage." >&2
    else
      v="$3"
    fi
  fi
  printf '%s' "$v"
}
VERSION=$(reglage version "$VERSION_ARG" "")
LISTE=$(reglage cartes "$CARTES_ARG" "$CARTES_DEFAUT")
MAJ=$(reglage maj_cartes "$MAJ_ARG" true)

mkdir -p "$TEMP" "$CARTES" || { echo "ERREUR : impossible de creer les dossiers de l'instance."; exit 1; }
rm -f "$TEMP"/* 2>/dev/null

# ── 1. Serveur TripleA ───────────────────────────────────────────────────────────
MOTIF_VERSION='^[0-9]{4}-[0-9]{2}\.[0-9]{1,4}\.[0-9]{1,7}$'
VERSION=$(printf '%s' "$VERSION" | tr -d '\000-\040\177')
case "${VERSION,,}" in
  ""|derniere|latest|"derni"*) VERSION="" ;;
esac
INSTALLEE=$(cat "$SERVEUR/.version" 2>/dev/null)
TAG=""
if [ -z "$VERSION" ]; then
  # releases/latest redirige vers .../releases/tag/<version> : pas d'API, pas de quota.
  URL=$(curl -fsSLI --retry 3 --connect-timeout 20 -o /dev/null -w '%{url_effective}' "https://github.com/$DEPOT/releases/latest" 2>/dev/null)
  TAG="${URL##*/releases/tag/}"
  if ! [[ "$TAG" =~ $MOTIF_VERSION ]]; then
    TAG=""
    echo "ATTENTION : github.com ne donne pas la derniere version de TripleA (reponse : ${URL:-aucune})."
  fi
elif [[ "$VERSION" =~ $MOTIF_VERSION ]]; then
  TAG="$VERSION"
  echo "Version de TripleA fixee dans les reglages : $TAG."
else
  echo "ATTENTION : « $VERSION » n'est pas un numero de version de TripleA (attendu : 2026-10.16.15815 par exemple, ou vide pour la derniere)."
fi

if [ -z "$TAG" ]; then
  if [ -f "$JAR" ]; then
    echo "On garde le serveur TripleA deja installe ($INSTALLEE). Relance Update plus tard."
  else
    echo "ERREUR : aucune version de TripleA a installer. Relance Update dans quelques minutes (ou corrige le reglage Version de TripleA)."
    exit 1
  fi
elif [ -f "$JAR" ] && [ "$INSTALLEE" = "$TAG" ]; then
  echo "Serveur TripleA $TAG deja installe : rien a faire."
else
  ZIP="$TEMP/game-headless.zip"
  echo "Telechargement du serveur TripleA $TAG (environ 32 Mo, github.com/$DEPOT/releases)..."
  if ! curl -fsSL --retry 3 --connect-timeout 20 -o "$ZIP" "https://github.com/$DEPOT/releases/download/$TAG/game-headless.zip"; then
    rm -f "$ZIP"
    if [ -f "$JAR" ]; then
      echo "ATTENTION : telechargement impossible (version $TAG introuvable ou github.com injoignable) : on garde le serveur installe ($INSTALLEE)."
    else
      echo "ERREUR : telechargement de game-headless.zip impossible pour la version $TAG (version inexistante ? les versions d'avant juin 2026 n'ont pas ce fichier)."
      exit 1
    fi
  else
    TAILLE=$(stat -c %s "$ZIP" 2>/dev/null || echo 0)
    if [ "$(head -c 2 "$ZIP")" != PK ] || [ "$TAILLE" -lt 10000000 ]; then
      rm -f "$ZIP"
      echo "ERREUR : le fichier recu n'est pas l'archive du serveur TripleA ($TAILLE octets). Rien n'a ete change."
      [ -f "$JAR" ] || exit 1
    else
      rm -rf "$SERVEUR.nouveau"
      mkdir -p "$SERVEUR.nouveau"
      if ! unzip -q -o "$ZIP" -d "$SERVEUR.nouveau" || [ ! -f "$SERVEUR.nouveau/bin/game-headless.jar" ]; then
        rm -rf "$SERVEUR.nouveau" "$ZIP"
        echo "ERREUR : archive du serveur illisible ou sans bin/game-headless.jar. Rien n'a ete change."
        [ -f "$JAR" ] || exit 1
      else
        rm -f "$ZIP"
        LUE=$(unzip -p "$SERVEUR.nouveau/bin/game-headless.jar" META-INF/triplea/product.properties 2>/dev/null \
          | sed -n 's/^version[[:space:]]*=[[:space:]]*\([^[:space:]]*\).*$/\1/p' | head -n 1)
        if [ "$LUE" != "$TAG" ]; then
          rm -rf "$SERVEUR.nouveau"
          echo "ERREUR : l'archive telechargee annonce la version « $LUE » au lieu de $TAG. Rien n'a ete change."
          [ -f "$JAR" ] || exit 1
        else
          # Exemples livres dans l'archive : ils ne marchent plus avec cette version
          # (nom du jar et options -P perimes), le lancement passe par lancer-triplea.sh.
          rm -f "$SERVEUR.nouveau/run_bot" "$SERVEUR.nouveau/run_bot.bat"
          echo "$TAG" > "$SERVEUR.nouveau/.version"
          if [ -n "$INSTALLEE" ] && [[ "$INSTALLEE" > "$TAG" ]]; then
            echo "ATTENTION : retour a une version plus ancienne ($INSTALLEE -> $TAG) : les parties sauvegardees par la version plus recente risquent de ne pas se charger."
          fi
          rm -rf "$SERVEUR"
          mv "$SERVEUR.nouveau" "$SERVEUR" || { echo "ERREUR : remplacement du serveur impossible."; exit 1; }
          echo "Serveur TripleA $TAG installe."
        fi
      fi
    fi
  fi
fi

# ── 2. Java (Eclipse Temurin, JRE) ──────────────────────────────────────────────
# Version de Java exigee = version des classes du serveur (octet 8 du .class - 44).
MAJEUR=$(unzip -p "$JAR" org/triplea/game/server/HeadlessGameRunner.class 2>/dev/null | head -c 8 | od -An -tu1 | tr -s ' ' '\n' | sed -n '9p')
if [[ "$MAJEUR" =~ ^[0-9]{2,3}$ ]] && [ "$MAJEUR" -ge 61 ]; then
  JAVA_VOULU=$((MAJEUR - 44))
else
  JAVA_VOULU=25
  echo "ATTENTION : version de Java exigee illisible dans le serveur : Java 25 par defaut."
fi
JAVA_ACTUEL=$(sed -n 's/^JAVA_VERSION="\([0-9]*\).*$/\1/p' "$JAVA_DIR/release" 2>/dev/null | head -n 1)
BUILD_ACTUEL=$(cat "$JAVA_DIR/.version-temurin" 2>/dev/null)
PERL_JAVA='
use strict; use warnings; use JSON::PP;
my ($fichier) = @ARGV;
open(my $f, "<:raw", $fichier) or die "lecture\n";
my $texte = do { local $/; <$f> }; close $f;
my $d = JSON::PP->new->utf8->decode($texte);
die "liste vide\n" unless ref $d eq "ARRAY";
for my $item (@$d) {
  next unless ref $item eq "HASH" && ref $item->{binary} eq "HASH";
  my $bin = $item->{binary};
  next unless ($bin->{image_type} // "") eq "jre" && ($bin->{os} // "") eq "linux" && ($bin->{architecture} // "") eq "x64";
  my $p = ref $bin->{package} eq "HASH" ? $bin->{package} : {};
  my ($lien, $somme, $v) = ($p->{link} // "", lc($p->{checksum} // ""), ref $item->{version} eq "HASH" ? ($item->{version}{openjdk_version} // "") : "");
  next unless $lien =~ m{^https://github\.com/adoptium/temurin[0-9]+-binaries/releases/download/[A-Za-z0-9%+._-]+/OpenJDK[A-Za-z0-9%+._-]+\.tar\.gz\z};
  next unless $somme =~ /^[0-9a-f]{64}\z/ && $v =~ /^[0-9][0-9A-Za-z.+-]{0,40}\z/;
  print "$lien\t$somme\t$v\n";
  exit 0;
}
die "aucun JRE linux x64\n";
'
INFOS=""
if curl -fsSL --retry 3 --connect-timeout 20 -o "$TEMP/java.json" \
     "https://api.adoptium.net/v3/assets/latest/$JAVA_VOULU/hotspot?architecture=x64&image_type=jre&os=linux&vendor=eclipse" 2>/dev/null; then
  INFOS=$(perl -e "$PERL_JAVA" "$TEMP/java.json" 2>/dev/null)
fi
rm -f "$TEMP/java.json"
IFS=$'\t' read -r J_LIEN J_SOMME J_BUILD <<< "$INFOS"
if [ -z "${J_LIEN:-}" ]; then
  if [ "$JAVA_ACTUEL" = "$JAVA_VOULU" ] && [ -x "$JAVA_DIR/bin/java" ]; then
    echo "ATTENTION : api.adoptium.net ne repond pas : on garde Java $JAVA_ACTUEL deja installe."
  else
    echo "ERREUR : impossible de trouver Java $JAVA_VOULU (Eclipse Temurin) sur api.adoptium.net. Relance Update dans quelques minutes."
    exit 1
  fi
elif [ "$JAVA_ACTUEL" = "$JAVA_VOULU" ] && [ "$BUILD_ACTUEL" = "$J_BUILD" ] && [ -x "$JAVA_DIR/bin/java" ]; then
  echo "Java $J_BUILD (Eclipse Temurin) deja installe : rien a faire."
else
  echo "Telechargement de Java $J_BUILD (Eclipse Temurin JRE, environ 60 Mo, github.com/adoptium)..."
  TGZ="$TEMP/java.tar.gz"
  if ! curl -fsSL --retry 3 --connect-timeout 20 -o "$TGZ" "$J_LIEN"; then
    rm -f "$TGZ"
    if [ "$JAVA_ACTUEL" = "$JAVA_VOULU" ] && [ -x "$JAVA_DIR/bin/java" ]; then
      echo "ATTENTION : telechargement de Java impossible : on garde Java $JAVA_ACTUEL deja installe."
    else
      echo "ERREUR : telechargement de Java impossible. Relance Update dans quelques minutes."
      exit 1
    fi
  elif [ "$(sha256sum "$TGZ" | cut -d' ' -f1)" != "$J_SOMME" ]; then
    rm -f "$TGZ"
    echo "ERREUR : l'empreinte SHA-256 de Java ne correspond pas a celle d'adoptium.net : fichier refuse."
    [ -x "$JAVA_DIR/bin/java" ] && [ "$JAVA_ACTUEL" = "$JAVA_VOULU" ] || exit 1
  else
    rm -rf "$JAVA_DIR.nouveau"
    mkdir -p "$JAVA_DIR.nouveau"
    if tar -xzf "$TGZ" -C "$JAVA_DIR.nouveau" --strip-components=1 && "$JAVA_DIR.nouveau/bin/java" -version >/dev/null 2>&1; then
      rm -f "$TGZ"
      echo "$J_BUILD" > "$JAVA_DIR.nouveau/.version-temurin"
      rm -rf "$JAVA_DIR"
      mv "$JAVA_DIR.nouveau" "$JAVA_DIR" || { echo "ERREUR : remplacement de Java impossible."; exit 1; }
      echo "Java $J_BUILD installe."
    else
      rm -rf "$JAVA_DIR.nouveau" "$TGZ"
      echo "ERREUR : Java telecharge mais inutilisable dans ce conteneur."
      [ -x "$JAVA_DIR/bin/java" ] && [ "$JAVA_ACTUEL" = "$JAVA_VOULU" ] || exit 1
    fi
  fi
fi

# ── 3. Cartes ───────────────────────────────────────────────────────────────────
# Noms separes par des virgules (ou points-virgules / retours a la ligne) ; espaces
# internes -> _, minuscules : « World War II Classic » = world_war_ii_classic.
DEMANDES=()
IFS=$'\n' read -r -d '' -a MORCEAUX < <(printf '%s' "$LISTE" | tr ',;' '\n\n' && printf '\0')
for m in "${MORCEAUX[@]}"; do
  m=$(printf '%s' "$m" | tr -d '\000-\037\177' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/[[:space:]]\{1,\}/_/g')
  [ -z "$m" ] && continue
  m="${m,,}"
  if [[ "$m" =~ ^[a-z0-9_.-]{1,100}$ ]]; then
    case " ${DEMANDES[*]} " in *" $m "*) ;; *) DEMANDES+=("$m") ;; esac
  else
    echo "ATTENTION : « $m » n'est pas un nom de carte valable (lettres sans accent, chiffres, _ . -) : ignore."
  fi
done
case "${MAJ,,}" in true|false) MAJ="${MAJ,,}" ;; *) MAJ=true ;; esac

if [ "${#DEMANDES[@]}" -eq 0 ]; then
  echo "Aucune carte demandee (reglage Cartes a installer vide) : rien a telecharger."
else
  PERL_CARTES='
use strict; use warnings; use JSON::PP;
my ($fichier, @demandes) = @ARGV;
open(my $f, "<:raw", $fichier) or die "lecture\n";
my $texte = do { local $/; <$f> }; close $f;
my $d = JSON::PP->new->utf8->decode($texte);
die "catalogue sans cartes\n" unless ref $d eq "HASH" && ref $d->{maps} eq "ARRAY" && @{$d->{maps}};
my %par_nom;
for my $c (@{$d->{maps}}) {
  next unless ref $c eq "HASH" && defined $c->{mapName} && !ref $c->{mapName};
  $par_nom{lc $c->{mapName}} //= $c;
}
for my $k (@demandes) {
  my $c = $par_nom{$k};
  if (!$c) { print "INCONNUE\t$k\n"; next }
  my ($nom, $url, $date) = ($c->{mapName}, $c->{downloadUrl} // "", $c->{lastCommitDateEpochMilli} // 0);
  my $taille = $c->{downloadSizeInBytes} // 0;
  $taille = 0 unless $taille =~ /^[0-9]{1,12}\z/;
  if ($nom !~ /^[A-Za-z0-9_.-]{1,100}\z/ || $nom =~ /^\./
      || $url !~ m{^https://github\.com/triplea-maps/[A-Za-z0-9_.-]+/archive/refs/heads/[A-Za-z0-9_.-]+\.zip\z}
      || $date !~ /^[0-9]{1,15}\z/) {
    print "REFUSEE\t$k\n"; next;
  }
  print "OK\t$k\t" . lc($nom) . "\t$url\t$date\t$taille\n";
}
'
  if ! curl -fsSL --retry 3 --connect-timeout 20 --max-time 120 -o "$TEMP/catalogue.json" "$CATALOGUE" 2>/dev/null \
     || ! RESULTATS=$(perl -e "$PERL_CARTES" "$TEMP/catalogue.json" "${DEMANDES[@]}" 2>/dev/null); then
    echo "ATTENTION : catalogue des cartes injoignable ou illisible ($CATALOGUE) : cartes inchangees. Relance Update plus tard."
  else
    declare -A DATES=()
    if [ -f "$MARQUE_CARTES" ]; then
      while IFS=$'\t' read -r d t || [ -n "$d" ]; do
        [[ "$d" =~ ^[a-z0-9_.-]{1,100}$ ]] && [[ "$t" =~ ^[0-9]{1,15}$ ]] && DATES["$d"]="$t"
      done < "$MARQUE_CARTES"
    fi
    NOUVELLES=0; ACTUELLES=0; ERREURS=0
    while IFS=$'\t' read -r etat cle dossier url date taille; do
      case "$etat" in
        INCONNUE)
          echo "ATTENTION : carte « $cle » absente du catalogue officiel : ignoree. Noms exacts : $CATALOGUE (champ mapName)."
          ERREURS=$((ERREURS + 1)); continue ;;
        REFUSEE)
          echo "ATTENTION : carte « $cle » : nom ou adresse inattendus dans le catalogue (seuls les depots github.com/triplea-maps sont acceptes) : ignoree."
          ERREURS=$((ERREURS + 1)); continue ;;
        OK) ;;
        *) continue ;;
      esac
      if [ -f "$CARTES/$dossier.zip" ]; then
        echo "Carte $dossier : deja telechargee, le serveur l'extraira au prochain demarrage."
        ACTUELLES=$((ACTUELLES + 1)); continue
      fi
      if [ -d "$CARTES/$dossier" ]; then
        if [ "$MAJ" = false ]; then
          echo "Carte $dossier : installee (mise a jour des cartes desactivee)."
          ACTUELLES=$((ACTUELLES + 1)); continue
        fi
        if [ "${DATES[$dossier]:-}" = "$date" ]; then
          echo "Carte $dossier : a jour."
          ACTUELLES=$((ACTUELLES + 1)); continue
        fi
        echo "Carte $dossier : nouvelle version dans le catalogue, telechargement..."
      else
        echo "Carte $dossier : telechargement ($((taille / 1048576 + 1)) Mo environ)..."
      fi
      Z="$TEMP/$dossier.zip"
      if curl -fsSL --retry 3 --connect-timeout 20 -o "$Z" "$url" && [ "$(head -c 2 "$Z")" = PK ] && unzip -tqq "$Z" >/dev/null 2>&1; then
        mv -f "$Z" "$CARTES/$dossier.zip"
        DATES["$dossier"]="$date"
        NOUVELLES=$((NOUVELLES + 1))
      else
        rm -f "$Z"
        echo "ATTENTION : carte $dossier : telechargement impossible ou archive abimee ($url). Ce qui etait installe est garde."
        ERREURS=$((ERREURS + 1))
      fi
    done <<< "$RESULTATS"
    {
      for d in "${!DATES[@]}"; do printf '%s\t%s\n' "$d" "${DATES[$d]}"; done
    } | sort > "$MARQUE_CARTES.nouveau" && mv -f "$MARQUE_CARTES.nouveau" "$MARQUE_CARTES"
    echo "Cartes : $NOUVELLES telechargee(s) (extraites par le serveur au prochain demarrage), $ACTUELLES deja la, $ERREURS probleme(s)."
  fi
  rm -f "$TEMP/catalogue.json"
fi
rmdir "$TEMP" 2>/dev/null

if [ ! -f "$JAR" ] || [ ! -x "$JAVA_DIR/bin/java" ]; then
  echo "ERREUR : installation incomplete (serveur ou Java absent)."
  exit 1
fi
echo "TripleA $(cat "$SERVEUR/.version" 2>/dev/null) pret, avec Java $(cat "$JAVA_DIR/.version-temurin" 2>/dev/null)."
exit 0
