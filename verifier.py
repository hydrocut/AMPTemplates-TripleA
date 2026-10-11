# -*- coding: utf-8 -*-
"""
Contrôle du template avant de le pousser (même rôle que ceux de PokerTH, ClassiCube, Wesnoth).

    python verifier.py

1. tous les JSON se parsent ;
2. le .kvp (ASCII, LF) ne référence que des fichiers présents, le port principal existe et
   arrive au lanceur, bloc Console.* / Limits.* complet, RegexMatch avec un motif non vide,
   arrêt par SIGTERM avec un délai > 60 s (minuterie d'arrêt de TripleA), conteneur
   obligatoire, AppConfigId et id du manifest = UUID neufs, App.MaxUsers réaliste, aucune
   variable {{$MaxUsers}} dans un fichier du template ;
3. chaque réglage exposé dans AMP est écrit une fois dans scripts/AMP_reglages-triplea.txt
   (rendu par AMP en reglages-triplea.txt) ET lu par le bon script (lanceur ou installeur,
   ligne de commande de l'Update comprise), et inversement ; défauts conformes aux règles de
   TripleA (nom « Bot... » de 7 à 21 caractères, commentaire de 14 au plus) ;
4. aller-retour réel avec le lanceur : on rend le modèle comme AMP (remplacement brut), on
   fait tourner le vrai lanceur avec un faux Java qui enregistre ses arguments, et on vérifie
   chaque argument : valeurs piégées ($( ), backticks, ;, guillemets, retour à la ligne qui
   tente d'injecter une autre clé, accents, noms trop courts ou trop longs, CRLF, variables
   non remplacées, fichier absent), port invalide, Java absent, arrêt par SIGTERM transmis
   au serveur, arrêts spontanés expliqués ;
5. les fichiers téléchargés à l'Update existent dans scripts/, à l'URL du dépôt du manifest,
   fins de ligne LF, `bash -n`, `perl -c`, aucun {{ ni eval dans les scripts ;
6. l'installeur, avec un faux curl qui sert des archives fabriquées ici : dernière version
   ou version fixée, contrôle de l'archive et de la version annoncée, Java de la bonne
   version avec empreinte SHA-256, cartes du catalogue (nouvelle, à jour, modifiée, mise à
   jour coupée, inconnue, adresse étrangère refusée, noms piégés), échecs sans dégât,
   données jamais touchées ;
7. les regex de console reconnaissent les lignes relevées sur le vrai serveur
   (2026-10.16.15815, essai local du 11/10/2026) et pas les autres.
"""
import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
import zipfile

ICI = os.path.dirname(os.path.abspath(__file__))
NOM = 'triplea'
MODELE = 'scripts/AMP_reglages-triplea.txt'
LANCEUR = 'scripts/lancer-triplea.sh'
INSTALLEUR = 'scripts/installer-triplea.sh'
soucis = []

# Réglage AMP -> script qui le lit.
CORRESPONDANCE = {
    'nom_bot': 'lanceur',
    'commentaire': 'lanceur',
    'memoire': 'lanceur',
    'version': 'installeur',
    'cartes': 'installeur',
    'maj_cartes': 'installeur',
}
TEXTES_LIBRES = ('nom_bot', 'commentaire', 'cartes', 'version')
MEMOIRES = {'256', '512', '1024', '2048'}
LOBBY = 'https://prod.triplea-game.org'


def lire(nom, binaire=False):
    chemin = os.path.join(ICI, nom)
    if binaire:
        with open(chemin, 'rb') as f:
            return f.read()
    with io.open(chemin, encoding='utf-8') as f:
        return f.read()


def py(motif):
    # AMP est en C# : (?<nom>...) ; Python veut (?P<nom>...).
    return re.compile(re.sub(r'\(\?<(?=[A-Za-z])', '(?P<', motif))


def est_uuid(v):
    try:
        return str(uuid.UUID(v)) == v.lower()
    except Exception:
        return False


def chemin_bash(p):
    return p.replace('\\', '/')


# ── 1. JSON ──────────────────────────────────────────────────────────────────
data = {}
for nom in ('manifest.json', NOM + 'config.json', NOM + 'metaconfig.json', NOM + 'ports.json', NOM + 'updates.json'):
    try:
        data[nom] = json.loads(lire(nom))
        print('ok   %-28s JSON valide' % nom)
    except Exception as e:
        soucis.append('%s : JSON invalide (%s)' % (nom, e))
if soucis:
    print('\n'.join('NON  ' + s for s in soucis))
    sys.exit(1)
config = data[NOM + 'config.json']
updates = data[NOM + 'updates.json']
ports = data[NOM + 'ports.json']
manifest = data['manifest.json']

# ── 2. kvp ───────────────────────────────────────────────────────────────────
kvp_brut = lire(NOM + '.kvp', binaire=True)
kvp = kvp_brut.decode('utf-8')
if b'\r' in kvp_brut:
    soucis.append(NOM + '.kvp : fins de ligne CRLF')
if any(b > 127 for b in kvp_brut):
    soucis.append(NOM + '.kvp : caractères non ASCII (les autres templates TeamKit restent en ASCII)')
cles = dict(l.split('=', 1) for l in kvp.splitlines() if '=' in l)
for ref in re.findall(r'@IncludeJson\[([^\]]+)\]', kvp):
    if not os.path.isfile(os.path.join(ICI, ref)):
        soucis.append('@IncludeJson[%s] : fichier absent' % ref)
for cle in ('Meta.ConfigManifest', 'Meta.MetaConfigManifest', 'Meta.ConfigRoot'):
    if not os.path.isfile(os.path.join(ICI, cles.get(cle, '?'))):
        soucis.append('%s pointe sur un fichier absent' % cle)
refs = {p['Ref'] for p in ports}
if cles.get('App.PrimaryApplicationPortRef') not in refs:
    soucis.append('PrimaryApplicationPortRef ne correspond à aucun port')
cmd = cles.get('App.CommandLineArgs', '')
if cmd != '"{{$FullBaseDir}}lancer-triplea.sh" {{$%s}}' % cles.get('App.PrimaryApplicationPortRef'):
    soucis.append('ligne de commande inattendue : %s' % cmd)
if [(p['Ref'], p['Port'], p['Protocol']) for p in ports] != [('GamePort', 3300, 'TCP')]:
    soucis.append('un seul port attendu : GamePort 3300/TCP')
elif 'joignable depuis internet' not in ports[0]['Description'] and 'joignable' not in ports[0]['Description']:
    soucis.append('description du port : dire que le lobby vérifie qu’il est joignable')
print('ok   ports                        %s' % ', '.join('%s %s/%s' % (p['Ref'], p['Port'], p['Protocol']) for p in ports))
ATTENDUES = ['App.SupportsUniversalSleep', 'App.WakeupMode', 'App.ApplicationReadyMode', 'Console.FilterMatchRegex',
             'Console.FilterMatchReplacement', 'Console.ThrowawayMessageRegex', 'Console.AppReadyRegex',
             'Console.UserJoinRegex', 'Console.UserLeaveRegex', 'Console.UserChatRegex', 'Console.UpdateAvailableRegex',
             'Console.PreConnectRegex', 'Console.ConnectIPRegex', 'Console.MetricsRegex', 'Console.HideFromConsoleRegex',
             'Console.SuppressLogAtStart', 'Console.UserActions', 'Limits.SleepMode', 'Limits.SleepOnStart',
             'Limits.SleepDelayMinutes', 'Limits.DozeDelay', 'Limits.AutoRetryCount', 'Limits.SleepStartThresholdSeconds']
absentes = [c for c in ATTENDUES if c not in cles]
if absentes:
    soucis.append('clés absentes du .kvp : ' + ', '.join(absentes))
else:
    print('ok   kvp complet                  les %d clés Console/Limits sont là' % len(ATTENDUES))
if cles.get('App.ApplicationReadyMode') != 'RegexMatch' or not cles.get('Console.AppReadyRegex'):
    soucis.append('RegexMatch avec une AppReadyRegex non vide attendue (sinon l’instance n’est jamais prête)')
if cles.get('Console.UserChatRegex'):
    soucis.append('pas de UserChatRegex : le chat de TripleA n’est pas écrit dans la console')
if (cles.get('App.ExitMethod'), cles.get('App.ExitString')) != ('SIGTERM', ''):
    soucis.append('arrêt attendu : ExitMethod=SIGTERM (le serveur n’a pas de console d’entrée)')
if not cles.get('App.ExitTimeout', '0').isdigit() or int(cles['App.ExitTimeout']) < 65:
    soucis.append('ExitTimeout trop court : TripleA enregistre la partie et se donne 60 s avant de couper')
if (cles.get('App.HasWriteableConsole'), cles.get('App.HasReadableConsole')) != ('False', 'True'):
    soucis.append('console : lecture seule (HasWriteableConsole=False, HasReadableConsole=True)')
if cles.get('Meta.URL') != manifest['url']:
    soucis.append('Meta.URL et manifest.json ne désignent pas le même dépôt')
if cles.get('Meta.SpecificDockerImage') != 'cubecoders/ampbase:debian' or cles.get('Meta.ContainerPolicy') != 'Required' \
        or cles.get('Meta.DockerRequired') != 'True':
    soucis.append('conteneur cubecoders/ampbase:debian obligatoire')
paquets = json.loads(cles.get('Meta.ExtraContainerPackages', '[]'))
if sorted(paquets) != ['ca-certificates', 'curl', 'perl', 'unzip']:
    soucis.append('ExtraContainerPackages : curl, ca-certificates, unzip et perl attendus : %r' % paquets)
mu = cles.get('App.MaxUsers', '0')
if not mu.isdigit() or not 2 <= int(mu) <= 64:
    soucis.append('App.MaxUsers irréaliste : %r (2 à 64)' % mu)
if '.tsvg' not in cles.get('App.SmartExcludeExemptions', ''):
    soucis.append('SmartExcludeExemptions : les sauvegardes .tsvg doivent être gardées')
# Identifiants neufs : jamais celui d'un autre template TeamKit.
if not est_uuid(cles.get('Meta.AppConfigId', '')) or not est_uuid(manifest.get('id', '')):
    soucis.append('Meta.AppConfigId et l’id du manifest doivent être des UUID')
if cles.get('Meta.AppConfigId', '').lower() == manifest.get('id', '').lower():
    soucis.append('AppConfigId et id du manifest identiques')
autres_ids = set()
for autre in glob.glob(os.path.join(ICI, '..', 'AMPTemplates-*')):
    if os.path.samefile(autre, ICI):
        continue
    for f in glob.glob(os.path.join(autre, '*.kvp')) + glob.glob(os.path.join(autre, 'manifest.json')):
        with io.open(f, encoding='utf-8', errors='replace') as h:
            autres_ids.update(re.findall(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', h.read().lower()))
if cles.get('Meta.AppConfigId', '').lower() in autres_ids or manifest.get('id', '').lower() in autres_ids:
    soucis.append('AppConfigId ou id du manifest déjà utilisé par un autre template')
print('ok   identifiants                 UUID neufs (%d identifiants des autres templates comparés)' % len(autres_ids))
# AMP ne remplace pas {{$MaxUsers}} dans un fichier rendu (vu sur Urban Terror, 10/10/2026).
for f in glob.glob(os.path.join(ICI, '*.json')) + glob.glob(os.path.join(ICI, 'scripts', '*')):
    if '$MaxUsers' in io.open(f, encoding='utf-8').read():
        soucis.append('%s : {{$MaxUsers}} interdit dans un fichier du template' % os.path.basename(f))

# ── 3. réglages ↔ modèle ↔ scripts ───────────────────────────────────────────
modele = lire(MODELE)
lanceur = lire(LANCEUR)
installeur = lire(INSTALLEUR)
dans_modele = re.findall(r'\{\{([^}]*)\}\}', modele)
params = {}
for c in config:
    f, p = c['FieldName'], c['ParamFieldName']
    if p in params:
        soucis.append('réglage en double : %s' % p)
    params[p] = c
    if f != p:
        soucis.append('%s : FieldName et ParamFieldName différents' % p)
    if dans_modele.count(p) != 1 or not re.search(r'^%s=\{\{%s\}\}$' % (p, p), modele, re.M):
        soucis.append('%s doit s’écrire %s={{%s}}, une seule fois, seul sur sa ligne' % (p, p, p))
    if p not in CORRESPONDANCE:
        soucis.append('%s : réglage inconnu de verifier.py' % p)
    elif CORRESPONDANCE[p] == 'lanceur':
        if not re.search(r'^\s+%s\) %s="\$val" ;;$' % (p, {'nom_bot': 'NOM_BOT', 'commentaire': 'COMMENTAIRE', 'memoire': 'MEMOIRE'}[p]), lanceur, re.M) \
                or 'nom_bot|commentaire|memoire)' not in lanceur:
            soucis.append('le lanceur ne lit pas %s' % p)
    else:
        if ('"{{%s}}"' % p) not in updates[-1]['UpdateSourceArgs'] or not re.search(r'=\$\(reglage %s "\$\w+_ARG"' % p, installeur):
            soucis.append('l’installeur ne reçoit pas %s (ligne de commande de l’Update + repli sur reglages-triplea.txt)' % p)
    if c['InputType'] == 'enum' and str(c.get('DefaultValue')) not in c.get('EnumValues', {}):
        soucis.append('%s : valeur par défaut absente des choix' % p)
    if c['InputType'] == 'checkbox' and (c['EnumValues'] != {'False': 'false', 'True': 'true'} or c['DefaultValue'] not in ('true', 'false')):
        soucis.append('%s : case à cocher attendue en true/false' % p)
    if c.get('IncludeInCommandLine') is not False:
        soucis.append('%s : IncludeInCommandLine doit être false (lu dans le fichier rendu)' % p)
    if not c.get('Category', '').startswith('TripleA:') or c.get('Required'):
        soucis.append('%s : catégorie TripleA, jamais obligatoire' % p)
if set(CORRESPONDANCE) - set(params):
    soucis.append('réglages attendus absents de la configuration : %s' % ', '.join(sorted(set(CORRESPONDANCE) - set(params))))
orphelins = set(dans_modele) - set(params)
if orphelins:
    soucis.append('{{...}} sans réglage dans AMP (ou variable AMP non remplacée dans un fichier) : %s' % ', '.join(sorted(orphelins)))
for l in modele.splitlines():
    if l.startswith('#') and '{{' in l:
        soucis.append('{{ dans un commentaire du modèle : AMP le remplacerait')
ordre = [l.split('=', 1)[0] for l in modele.splitlines() if '=' in l and not l.startswith('#')]
for p in ordre:
    if p not in TEXTES_LIBRES and any(ordre.index(p) > ordre.index(t) for t in TEXTES_LIBRES if t in ordre):
        soucis.append('%s doit venir avant les champs de texte libre dans le modèle (la première ligne compte)' % p)
if set(params['memoire']['EnumValues']) != MEMOIRES or 'case "$MEMOIRE" in\n  256|512|1024|2048) ;;' not in lanceur:
    soucis.append('mémoire : mêmes choix dans AMP et dans le lanceur (256, 512, 1024, 2048)')
nb = params['nom_bot']['DefaultValue']
if not (nb.startswith('Bot') and 7 <= len(nb) <= 21 and re.fullmatch(r'[A-Za-z0-9_-]+', nb)) or 'NOM_DEFAUT="%s"' % nb not in lanceur:
    soucis.append('nom du bot par défaut : « Bot... », 7 à 21 caractères, identique dans le lanceur')
cm = params['commentaire']['DefaultValue']
if len(cm) > 14 or 'COMMENTAIRE_DEFAUT="%s"' % cm not in lanceur:
    soucis.append('commentaire par défaut : 14 caractères au plus, identique dans le lanceur')
if 'CARTES_DEFAUT="%s"' % params['cartes']['DefaultValue'] not in installeur:
    soucis.append('cartes par défaut : même liste dans AMP et dans l’installeur')
if params['version']['DefaultValue'] != '' or params['maj_cartes']['DefaultValue'] != 'true' or params['memoire']['DefaultValue'] != '512':
    soucis.append('défauts attendus : dernière version, mise à jour des cartes, 512 Mo')
meta = data[NOM + 'metaconfig.json'][0]
racine = cles['App.RootDir'].strip('./').strip('/')
if meta.get('ConfigType') != 'template' or meta.get('ConfigFileTemplate') != racine + '/AMP_reglages-triplea.txt':
    soucis.append('metaconfig : ConfigFileTemplate devrait être %s/AMP_reglages-triplea.txt' % racine)
if meta.get('ConfigFile') != 'reglages-triplea.txt' or 'REGLAGES="$ICI/reglages-triplea.txt"' not in lanceur \
        or 'REGLAGES="$ICI/reglages-triplea.txt"' not in installeur:
    soucis.append('le fichier rendu par AMP (ConfigFile) n’est pas celui que lisent les scripts')
readme = lire('README.md')
for besoin in ('## How players join', '## Adding a map', '## Known limits', '## Résumé en français', 'Connect to Networked Game',
               'Login Without An Account', 'Select Game', 'GPL-3.0', 'not reachable from the internet', 'triplea.server.password',
               'Download Maps', '3300'):
    if besoin not in readme:
        soucis.append('README : %r absent' % besoin)
if 'mot de passe' not in cles.get('Meta.Description', '').lower():
    soucis.append('description du template : dire qu’il n’y a pas de mot de passe de partie')
print('ok   correspondance               %d réglages : AMP -> %s -> scripts' % (len(params), MODELE))

bash = shutil.which('bash')
defauts = {p: str(c.get('DefaultValue', '')) for p, c in params.items()}


def par_fichier(dossier, script, args):
    """Arguments passés tels quels, comme AMP sous Linux : écrits dans un fichier (NUL entre
    eux) et relus par bash. Sous Windows, le bash de Git/Cygwin développerait lui-même
    {{...}}, les jokers et les guillemets d'une ligne de commande reçue de Python."""
    f = os.path.join(dossier, 'arguments.bin')
    with open(f, 'wb') as h:
        h.write(b''.join(a.encode('utf-8') + b'\0' for a in args))
    return [bash, '-c', 'mapfile -d "" -t A < "$1"; exec bash "$0" "${A[@]}"', chemin_bash(script), chemin_bash(f)]


def rendre(valeurs):
    t = modele
    for p, v in valeurs.items():
        t = t.replace('{{%s}}' % p, v)
    return t


# ── 4. aller-retour réel avec le lanceur (faux Java) ──────────────────────────
FAUX_JAVA = r'''#!/bin/bash
# Faux Java : enregistre ses arguments (un par ligne, NUL entre eux) et son environnement.
printf '%s\0' "$@" > "$TK_ARGS"
printf '%s' "${MAPS_FOLDER-<absent>}" > "$TK_ARGS.maps"
printf '%s' "${BOT_NAME-<absent>}" > "$TK_ARGS.env"
echo "22:00:00.000 [main] INFO  o.t.game.server.HeadlessGameServer - Headless Start"
case "${TK_FAUX_JAVA:-fin}" in
  code1) echo "22:00:01.000 [main] ERROR o.t.game.server.HeadlessGameRunner - Failed to run game server"; exit 1 ;;
  code0) exit 0 ;;
  attend)
    trap 'echo "22:00:09.000 [Thread-2] INFO  o.t.game.server.HeadlessGameServer - Running ShutdownHook."; exit 143' TERM
    echo "22:00:02.000 [main] INFO  o.t.game.server.HeadlessGameServer - Waiting for users to connect."
    for _ in $(seq 1 300); do sleep 0.1; done
    exit 99 ;;
esac
exit 0
'''


def instance(dossier, avec_java=True):
    inst = os.path.join(dossier, 'triplea')
    os.makedirs(os.path.join(inst, 'triplea-serveur', 'bin'))
    with io.open(os.path.join(inst, 'lancer-triplea.sh'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(lanceur)
    with open(os.path.join(inst, 'triplea-serveur', 'bin', 'game-headless.jar'), 'wb') as f:
        f.write(b'PK')
    with open(os.path.join(inst, 'triplea-serveur', '.version'), 'w', newline='\n') as f:
        f.write('2026-10.16.15815\n')
    if avec_java:
        os.makedirs(os.path.join(inst, 'java', 'bin'))
        with io.open(os.path.join(inst, 'java', 'bin', 'java'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(FAUX_JAVA)
        os.chmod(os.path.join(inst, 'java', 'bin', 'java'), 0o755)
    return inst


def lancer(texte_reglages, args, mode='fin', avec_java=True, avant=None):
    """Lance le vrai lanceur ; texte_reglages=None : pas de fichier rendu par AMP."""
    dossier = tempfile.mkdtemp(prefix='tk-triplea-')
    inst = instance(dossier, avec_java)
    if texte_reglages is not None:
        with io.open(os.path.join(inst, 'reglages-triplea.txt'), 'w', encoding='utf-8', newline='') as f:
            f.write(texte_reglages)
    if avant:
        avant(inst)
    trace = os.path.join(dossier, 'args')
    env = dict(os.environ, TK_ARGS=chemin_bash(trace), TK_FAUX_JAVA=mode, BOT_NAME='Bot_Intrus_01')
    r = subprocess.run(par_fichier(dossier, os.path.join(inst, 'lancer-triplea.sh'), args), capture_output=True, timeout=60, env=env, cwd=dossier)
    sortie = r.stdout.decode('utf-8', 'replace') + r.stderr.decode('utf-8', 'replace')
    arguments = None
    if os.path.exists(trace):
        arguments = open(trace, 'rb').read().decode('utf-8').split('\0')[:-1]
    return dossier, inst, r.returncode, sortie, arguments


def props(arguments):
    return {a[2:].split('=', 1)[0]: a[2:].split('=', 1)[1] for a in arguments if a.startswith('-D')}


def valeurs(**v):
    vals = dict(defauts)
    vals.update(v)
    return rendre(vals)


if bash:
    dossiers = []
    try:
        # a. valeurs par défaut : la liste exacte des arguments
        d, inst, code, out, a = lancer(valeurs(), ['3300'])
        dossiers.append(d)
        # Chemin de l'instance tel que bash le voit (/tmp/... sous Git Bash) : tiré de user.home.
        racine = (a or ['', '', '', '', '-Duser.home=?/donnees'])[4][len('-Duser.home='):-len('/donnees')]
        if not racine.endswith('/' + os.path.basename(d) + '/triplea'):
            soucis.append('lanceur : user.home hors de l’instance : %r' % racine)
        attendu = ['-Xmx512m', '-Xss1250k', '-Djava.awt.headless=true', '-Djava.net.preferIPv4Stack=true',
                   '-Duser.home=%s/donnees' % racine, '-Djava.util.prefs.systemRoot=%s/donnees/.java-systeme' % racine,
                   '-Dlogback.statusListenerClass=ch.qos.logback.core.status.NopStatusListener',
                   '-Dtriplea.name=Bot_TeamKit_FR', '-Dtriplea.port=3300', '-Dtriplea.lobby.uri=' + LOBBY,
                   '-Dtriplea.lobby.game.comments=TeamKit FR', '-Dtriplea.exit.on.game.end=false',
                   '-jar', '%s/triplea-serveur/bin/game-headless.jar' % racine]
        if code or a != attendu:
            soucis.append('lanceur, défauts : code %d, arguments %r, sortie %r' % (code, a, out))
        maps = open(os.path.join(d, 'args.maps'), encoding='utf-8').read()
        if maps != racine + '/cartes' or open(os.path.join(d, 'args.env'), encoding='utf-8').read() != '<absent>':
            soucis.append('lanceur : MAPS_FOLDER = cartes/ attendu et BOT_NAME hérité effacé (%r)' % maps)
        if 'aucune carte' not in out or not os.path.isdir(os.path.join(inst, 'donnees')):
            soucis.append('lanceur : prévenir qu’aucune carte n’est installée, créer donnees/')
        # b. valeurs piégées : rien n'est exécuté, chaque valeur reste un seul argument
        PIEGE = '$(touch PWNED)`touch PWNED2`;touch PWNED3 "\' & | > x'
        for nom_bot, attendu_nom in [
            (PIEGE, 'Bot_touch_PWNEDtouch_'),
            ('kevin', 'Bot_kevin'),
            ('bot kévin à la plage', 'Bot_kevin_a_la_plage'),
            ('BOT-Équipe', 'Bot-Equipe'),
            ('Bot', 'Bot_TeamKit_FR'),
            ('BOTxx', 'Bot_TeamKit_FR'),
            ('', 'Bot_TeamKit_FR'),
            ('Bot_' + 'x' * 40, 'Bot_' + 'x' * 17),
            ('Bot_TeamKit_FR', 'Bot_TeamKit_FR'),
        ]:
            d, inst, code, out, a = lancer(valeurs(nom_bot=nom_bot), ['3300'])
            dossiers.append(d)
            p = props(a or [])
            if code or p.get('triplea.name') != attendu_nom or len(a) != len(attendu):
                soucis.append('lanceur, nom %r : %r attendu, reçu %r (code %d)' % (nom_bot, attendu_nom, p.get('triplea.name'), code))
            n = p.get('triplea.name', '')
            if not (n.startswith('Bot') and 7 <= len(n) <= 21):
                soucis.append('lanceur : nom refusé par TripleA transmis : %r' % n)
        for comm, attendu_comm in [
            (PIEGE, '$(touch PWNED)'),
            ('Équipe française de TeamKit', 'Equipe francai'),
            ('  TeamKit   FR  ', 'TeamKit FR'),
            ('', ''),
            ('Parties 1940 !', 'Parties 1940 !'),
        ]:
            d, inst, code, out, a = lancer(valeurs(commentaire=comm), ['3300'])
            dossiers.append(d)
            c = props(a or []).get('triplea.lobby.game.comments')
            if code or c != attendu_comm or len(c or '') > 14:
                soucis.append('lanceur, commentaire %r : %r attendu, reçu %r' % (comm, attendu_comm, c))
        for mem, attendu_mem in [('1024', '-Xmx1024m'), ('4096', '-Xmx512m'), ('512m; rm -rf /', '-Xmx512m'), ('', '-Xmx512m')]:
            d, inst, code, out, a = lancer(valeurs(memoire=mem), ['3300'])
            dossiers.append(d)
            if code or not a or a[0] != attendu_mem:
                soucis.append('lanceur, mémoire %r : %s attendu, reçu %r' % (mem, attendu_mem, a and a[0]))
        # c. retour à la ligne dans un texte libre qui tente d'injecter une autre clé
        d, inst, code, out, a = lancer(valeurs(commentaire='x\nmemoire=2048\nnom_bot=Bot_Pirate_1', nom_bot='Bot_Vrai_Nom', memoire='1024'), ['3300'])
        dossiers.append(d)
        p = props(a or [])
        if code or a[0] != '-Xmx512m' or p.get('triplea.name') != 'Bot_TeamKit_FR' or p.get('triplea.lobby.game.comments') != 'x' \
                or 'nom_bot apparait plusieurs fois' not in out:
            soucis.append('lanceur : une clé glissée dans un texte libre ne doit pas être crue (défaut pour la clé en double) : %r %r' % (a, out))
        # d. CRLF, variables non remplacées, fichier absent
        d, inst, code, out, a = lancer(valeurs(nom_bot='Bot_Windows').replace('\n', '\r\n'), ['3300'])
        dossiers.append(d)
        if code or props(a or []).get('triplea.name') != 'Bot_Windows' or a[0] != '-Xmx512m':
            soucis.append('lanceur : fichier rendu en CRLF mal lu : %r' % a)
        d, inst, code, out, a = lancer(modele, ['3300'])
        dossiers.append(d)
        p = props(a or [])
        if code or p.get('triplea.name') != 'Bot_TeamKit_FR' or p.get('triplea.lobby.game.comments') != 'TeamKit FR' or a[0] != '-Xmx512m':
            soucis.append('lanceur : variables laissées telles quelles par AMP = défauts : %r' % a)
        d, inst, code, out, a = lancer(None, ['3300'])
        dossiers.append(d)
        if code or props(a or []).get('triplea.name') != 'Bot_TeamKit_FR' or 'absent' not in out:
            soucis.append('lanceur sans fichier de réglages : défauts attendus : %r' % out)
        # e. port : invalide refusé, zéros en tête retirés ; Java absent
        for port in ('0', '70000', '33a', '$(id)', ''):
            d, inst, code, out, a = lancer(valeurs(), [port] if port else [])
            dossiers.append(d)
            if port and (code != 1 or a is not None):
                soucis.append('lanceur, port %r : refus attendu' % port)
            if not port and props(a or []).get('triplea.port') != '3300':
                soucis.append('lanceur sans port : 3300 attendu')
        d, inst, code, out, a = lancer(valeurs(), ['03301'])
        dossiers.append(d)
        if props(a or []).get('triplea.port') != '3301':
            soucis.append('lanceur, port 03301 : 3301 attendu')
        d, inst, code, out, a = lancer(valeurs(), ['3300'], avec_java=False)
        dossiers.append(d)
        if code != 1 or 'Lance Update' not in out:
            soucis.append('lanceur sans Java : refus avec « Lance Update » attendu')
        # f. cartes : comptées, zip en attente signalé
        def poser_cartes(inst):
            # extraite par le serveur (cartes/<nom>/<nom>-master/map.yml, vu le 11/10/2026),
            # posée à la main (map.yml directement dedans), dossier vide, zip en attente
            os.makedirs(os.path.join(inst, 'cartes', 'world_war_ii_classic', 'world_war_ii_classic-master'))
            open(os.path.join(inst, 'cartes', 'world_war_ii_classic', 'world_war_ii_classic-master', 'map.yml'), 'w').close()
            os.makedirs(os.path.join(inst, 'cartes', 'ma_carte'))
            open(os.path.join(inst, 'cartes', 'ma_carte', 'map.yml'), 'w').close()
            os.makedirs(os.path.join(inst, 'cartes', 'vide'))
            open(os.path.join(inst, 'cartes', 'world_war_ii_v3.zip'), 'wb').close()
        d, inst, code, out, a = lancer(valeurs(), ['3300'], avant=poser_cartes)
        dossiers.append(d)
        if '2 carte(s) installee(s), 1 a extraire' not in out:
            soucis.append('lanceur : décompte des cartes faux : %r' % out)
        # g. arrêts spontanés expliqués
        d, inst, code, out, a = lancer(valeurs(), ['3300'], mode='code1')
        dossiers.append(d)
        if code != 1 or 'not reachable from the internet' not in out:
            soucis.append('lanceur : arrêt en erreur non expliqué : %r' % out)
        d, inst, code, out, a = lancer(valeurs(), ['3300'], mode='code0')
        dossiers.append(d)
        if code != 0 or 'moderateur' not in out:
            soucis.append('lanceur : arrêt sans erreur (modérateur du lobby) non expliqué : %r' % out)
        # h. SIGTERM d'AMP : transmis à Java, qui enregistre et s'arrête ; code 0
        dossier = tempfile.mkdtemp(prefix='tk-triplea-')
        dossiers.append(dossier)
        inst = instance(dossier)
        with io.open(os.path.join(inst, 'reglages-triplea.txt'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(valeurs())
        script = ('bash "$0" 3300 > "$1" 2>&1 & P=$!; for _ in $(seq 1 100); do grep -q "Waiting for users" "$1" && break; sleep 0.1; done; '
                  'kill -TERM $P; wait $P; echo "code=$?" >> "$1"')
        sortie = os.path.join(dossier, 'sortie.txt')
        env = dict(os.environ, TK_ARGS=chemin_bash(os.path.join(dossier, 'args')), TK_FAUX_JAVA='attend')
        subprocess.run([bash, '-c', script, chemin_bash(os.path.join(inst, 'lancer-triplea.sh')), chemin_bash(sortie)],
                       capture_output=True, timeout=60, env=env)
        out = io.open(sortie, encoding='utf-8', errors='replace').read()
        if 'Running ShutdownHook' not in out or 'TeamKit : serveur arrete.' not in out or 'code=0' not in out:
            soucis.append('lanceur : SIGTERM non transmis ou mauvais code de sortie : %r' % out)
        # aucun fichier créé par une valeur piégée
        for d in dossiers:
            for racine_, _, fichiers in os.walk(d):
                if any(f.startswith('PWNED') for f in fichiers):
                    soucis.append('lanceur : une valeur a été EXÉCUTÉE (%s)' % racine_)
        print('ok   lanceur                      %d essais réels (faux Java) : arguments, pièges, CRLF, ports, arrêts' % len(dossiers))
    except Exception as e:
        soucis.append('lanceur : essai interrompu (%r)' % e)
    finally:
        for d in dossiers:
            shutil.rmtree(d, ignore_errors=True)
else:
    soucis.append('bash introuvable : essais réels impossibles')

# ── 5. fichiers téléchargés à l'Update, scripts ──────────────────────────────
depot = manifest['url'].replace('https://github.com/', '')
fetch = [e for e in updates if e['UpdateSource'] == 'FetchURL']
for e in fetch:
    attendu = 'https://raw.githubusercontent.com/%s/main/scripts/%s' % (depot, e['UpdateSourceArgs'])
    if e['UpdateSourceData'] != attendu:
        soucis.append('URL inattendue pour %s : %s' % (e['UpdateSourceArgs'], e['UpdateSourceData']))
    elif not os.path.isfile(os.path.join(ICI, 'scripts', e['UpdateSourceArgs'])):
        soucis.append('scripts/%s absent du dépôt' % e['UpdateSourceArgs'])
    else:
        print('ok   téléchargé à l’Update        scripts/%s' % e['UpdateSourceArgs'])
if {e['UpdateSourceArgs'] for e in fetch} != {'AMP_reglages-triplea.txt', 'lancer-triplea.sh', 'installer-triplea.sh'}:
    soucis.append('l’Update doit déposer les deux scripts et le modèle des réglages')
dernier = updates[-1]
if dernier['UpdateSource'] != 'Executable' or dernier['UpdateSourceData'] != '/bin/bash' or dernier['UpdateSourceArgs'] != \
        '"{{$FullBaseDir}}installer-triplea.sh" "{{$FullBaseDir}}" "{{version}}" "{{cartes}}" "{{maj_cartes}}"':
    soucis.append('la dernière étape de l’Update doit lancer installer-triplea.sh avec version, cartes, maj_cartes')
for nom in sorted(glob.glob(os.path.join(ICI, 'scripts', '*'))) + [os.path.join(ICI, f) for f in os.listdir(ICI) if f.endswith(('.json', '.kvp', '.py', '.md'))]:
    rel = os.path.relpath(nom, ICI).replace('\\', '/')
    contenu = lire(rel)
    if b'\r' in lire(rel, binaire=True):
        soucis.append('%s : fins de ligne Windows (CRLF)' % rel)
    if rel.startswith('scripts/') and '{{$' in contenu:
        soucis.append('%s contient {{$...}} : AMP ne remplace pas ses variables dans les fichiers livrés' % rel)
    if rel.endswith('.sh'):
        if '{{' in contenu:
            soucis.append('%s contient {{ : AMP pourrait le remplacer' % rel)
        if re.search(r'\beval\b', contenu):
            soucis.append('%s : eval interdit (les valeurs viennent de l’onglet Configuration)' % rel)
        if not contenu.startswith('#!/bin/bash\n'):
            soucis.append('%s : doit commencer par #!/bin/bash' % rel)
        if bash:
            r = subprocess.run([bash, '-n', nom], capture_output=True, text=True)
            if r.returncode:
                soucis.append('bash -n %s : %s' % (rel, r.stderr.strip()))
            else:
                print('ok   bash -n                      %s' % rel)
perl_bin = shutil.which('perl')
for nom_var in ('PERL_JAVA', 'PERL_CARTES'):
    m = re.search(r"^\s*%s='\n(.*?)\n'$" % nom_var, installeur, re.S | re.M)
    if not m or "'" in m.group(1):
        soucis.append('code perl %s introuvable, ou avec une apostrophe (il est entre apostrophes pour bash)' % nom_var)
        continue
    code_perl = m.group(1)
    if re.search(r'^\s*use (?!strict|warnings|JSON::PP)', code_perl, re.M):
        soucis.append('%s : aucun module hors strict, warnings, JSON::PP' % nom_var)
    if perl_bin:
        with tempfile.NamedTemporaryFile('w', suffix='.pl', delete=False, encoding='utf-8', newline='\n') as f:
            f.write(code_perl)
        r = subprocess.run([perl_bin, '-c', f.name], capture_output=True, text=True)
        os.remove(f.name)
        if r.returncode:
            soucis.append('perl -c %s : %s' % (nom_var, r.stderr.strip()))
        else:
            print('ok   perl -c                      %s' % nom_var)
for besoin, pourquoi in [
    ('"$JAVA" "${ARGS[@]}" </dev/null &', 'arguments passés en tableau, entrée = /dev/null'),
    ('setpriv --pdeathsig TERM -- "$JAVA" "${ARGS[@]}"', 'Java s’arrête si le script est tué net'),
    ('kill -TERM "$PID"', 'SIGTERM transmis au serveur (il enregistre la partie)'),
    ('"-Dtriplea.lobby.uri=$LOBBY"', 'lobby officiel'),
    ('unset BOT_NAME BOT_PORT BOT_COMMENT BOT_LOBBY_URI', 'variables d’environnement de TripleA neutralisées'),
    ('export MAPS_FOLDER="$CARTES"', 'TripleA lit le dossier des cartes dans l’environnement'),
]:
    if besoin not in lanceur:
        soucis.append('lanceur : %s absent (%s)' % (besoin, pourquoi))
for besoin, pourquoi in [
    ('sha256sum "$TGZ"', 'empreinte de Java vérifiée'),
    ('META-INF/triplea/product.properties', 'version annoncée par l’archive vérifiée'),
    ('https://github\\.com/triplea-maps/', 'cartes : seulement les dépôts officiels'),
    ('unzip -tqq "$Z"', 'carte : archive testée avant d’être posée'),
]:
    if besoin not in installeur:
        soucis.append('installeur : %s absent (%s)' % (besoin, pourquoi))


# ── 6. installeur (faux curl, archives fabriquées) ───────────────────────────
FAUX_CURL = r'''#!/bin/bash
sortie=""; url=""; format=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) sortie="$2"; shift 2 ;;
    -w) format="$2"; shift 2 ;;
    -H|--retry|--connect-timeout|--max-time) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
echo "$url" >> "$TK_JOURNAL_CURL"
[ "$TK_FAUX_CURL" = echec ] && exit 22
servir() { [ -f "$TK_FIX/$1" ] || exit 22; if [ "$TK_FAUX_CURL" = html ] && [ "$2" = gros ]; then printf '<html>404</html>' > "$sortie"; else cp "$TK_FIX/$1" "$sortie"; fi; }
case "$url" in
  https://github.com/triplea-game/triplea/releases/latest)
    [ -n "$format" ] && printf 'https://github.com/triplea-game/triplea/releases/tag/%s' "$TK_TAG" ;;
  https://github.com/triplea-game/triplea/releases/download/*/game-headless.zip)
    t="${url#*/download/}"; servir "headless-${t%%/*}.zip" gros ;;
  https://api.adoptium.net/v3/assets/latest/*) servir java.json ;;
  https://github.com/adoptium/*) servir jre.tar.gz gros ;;
  https://prod.triplea-game.org/support/maps/listing) servir catalogue.json ;;
  https://github.com/triplea-maps/*) n="${url#https://github.com/triplea-maps/}"; servir "carte-${n%%/*}.zip" ;;
  *) exit 22 ;;
esac
exit 0
'''
TAG = '2026-10.16.15815'
ANCIEN = '2026-09.16.15802'


def faux_jar(version, majeur=69):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\nMain-Class: org.triplea.game.server.HeadlessGameRunner\n')
        z.writestr('META-INF/triplea/product.properties', 'version = %s\n' % version)
        z.writestr('org/triplea/game/server/HeadlessGameRunner.class', bytes([0xCA, 0xFE, 0xBA, 0xBE, 0, 0, 0, majeur]) + b'\0' * 32)
    return b.getvalue()


def faux_headless(chemin, version_annoncee):
    with zipfile.ZipFile(chemin, 'w') as z:
        z.writestr('.triplea-root', ' ')
        z.writestr('run_bot', '#!/bin/bash\n')
        z.writestr('run_bot.bat', 'rem\r\n')
        z.writestr('bin/game-headless.jar', faux_jar(version_annoncee))
        z.writestr(zipfile.ZipInfo('bin/remplissage'), os.urandom(10200000))


def faux_jre(chemin):
    with tarfile.open(chemin, 'w:gz') as t:
        for nom, contenu, mode in [
            ('jdk-25.0.4.1+1-jre/bin/java', b'#!/bin/bash\necho \'openjdk version "25.0.4.1" 2026-08-18 LTS\' >&2\n', 0o755),
            ('jdk-25.0.4.1+1-jre/release', b'JAVA_VERSION="25.0.4.1"\nIMPLEMENTOR="Eclipse Adoptium"\n', 0o644),
        ]:
            i = tarfile.TarInfo(nom)
            i.size = len(contenu)
            i.mode = mode
            t.addfile(i, io.BytesIO(contenu))
    return hashlib.sha256(open(chemin, 'rb').read()).hexdigest()


def java_json(somme, build='25.0.4.1+1-LTS'):
    return json.dumps([{
        'binary': {'architecture': 'x64', 'image_type': 'jre', 'os': 'linux', 'package': {
            'checksum': somme, 'name': 'OpenJDK25U-jre_x64_linux_hotspot_25.0.4.1_1.tar.gz', 'size': 61718288,
            'link': 'https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.4.1%2B1/OpenJDK25U-jre_x64_linux_hotspot_25.0.4.1_1.tar.gz'}},
        'version': {'openjdk_version': build}}])


def carte_zip(chemin, nom, marque=b'v1'):
    with zipfile.ZipFile(chemin, 'w') as z:
        z.writestr('%s-master/map.yml' % nom, 'map_name: %s\n' % nom)
        z.writestr('%s-master/games/jeu.xml' % nom, marque)


def catalogue(dates, en_plus=()):
    cartes = [{'mapName': n, 'downloadUrl': 'https://github.com/triplea-maps/%s/archive/refs/heads/master.zip' % n,
               'lastCommitDateEpochMilli': dt, 'downloadSizeInBytes': 4343648, 'description': '', 'mapTags': []}
              for n, dt in dates.items()]
    return json.dumps({'maps': cartes + list(en_plus)})


def installer(dossier, args, mode='normal', tag=TAG, reglages=None):
    inst = os.path.join(dossier, 'triplea')
    os.makedirs(inst, exist_ok=True)
    outils = os.path.join(dossier, 'outils')
    os.makedirs(outils, exist_ok=True)
    with io.open(os.path.join(outils, 'curl'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(FAUX_CURL)
    os.chmod(os.path.join(outils, 'curl'), 0o755)
    if reglages is not None:
        with io.open(os.path.join(inst, 'reglages-triplea.txt'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(reglages)
    journal = os.path.join(dossier, 'curl.txt')
    if os.path.exists(journal):
        os.remove(journal)
    env = dict(os.environ, TK_FAUX_CURL=mode, TK_JOURNAL_CURL=chemin_bash(journal), TK_FIX=chemin_bash(os.path.join(dossier, 'fix')), TK_TAG=tag)
    env['PATH'] = outils + os.pathsep + env.get('PATH', '')
    r = subprocess.run(par_fichier(dossier, os.path.join(ICI, INSTALLEUR), [chemin_bash(inst) + '/'] + args), capture_output=True, timeout=120, env=env, cwd=dossier)
    urls = io.open(journal, encoding='utf-8').read().split() if os.path.exists(journal) else []
    return r.returncode, r.stdout.decode('utf-8', 'replace') + r.stderr.decode('utf-8', 'replace'), urls


def empreintes(dossier):
    res = {}
    for racine_, _, fichiers in os.walk(dossier):
        for f in fichiers:
            with open(os.path.join(racine_, f), 'rb') as h:
                res[os.path.relpath(os.path.join(racine_, f), dossier)] = hashlib.md5(h.read()).hexdigest()
    return res


ZIP_URL = 'https://github.com/triplea-game/triplea/releases/download/%s/game-headless.zip'
LATEST = 'https://github.com/triplea-game/triplea/releases/latest'
CAT = 'https://prod.triplea-game.org/support/maps/listing'
QUATRE = ['world_war_ii_classic', 'world_war_ii_revised', 'world_war_ii_v3', 'world_war_ii_global']
if bash:
    dossier = tempfile.mkdtemp(prefix='tk-triplea-inst-')
    try:
      try:
        fix = os.path.join(dossier, 'fix')
        os.makedirs(fix)
        inst = os.path.join(dossier, 'triplea')
        faux_headless(os.path.join(fix, 'headless-%s.zip' % TAG), TAG)
        faux_headless(os.path.join(fix, 'headless-%s.zip' % ANCIEN), ANCIEN)
        faux_headless(os.path.join(fix, 'headless-2026-08.16.15700.zip'), '2026-08.16.99999')   # annonce une autre version
        somme = faux_jre(os.path.join(fix, 'jre.tar.gz'))
        with open(os.path.join(fix, 'java.json'), 'w') as f:
            f.write(java_json(somme))
        for n in QUATRE + ['pacific_1942']:
            carte_zip(os.path.join(fix, 'carte-%s.zip' % n), n)
        etrangere = {'mapName': 'carte_piege', 'downloadUrl': 'https://evil.example/carte.zip', 'lastCommitDateEpochMilli': 1}
        remontee = {'mapName': '../../etc', 'downloadUrl': 'https://github.com/triplea-maps/x/archive/refs/heads/master.zip', 'lastCommitDateEpochMilli': 1}
        dates = {n: 1000 + i for i, n in enumerate(QUATRE + ['pacific_1942'])}
        with open(os.path.join(fix, 'catalogue.json'), 'w') as f:
            f.write(catalogue(dates, [etrangere, remontee]))
        os.makedirs(os.path.join(inst, 'donnees', 'triplea', 'savedGames', 'autoSave'))
        with open(os.path.join(inst, 'donnees', 'triplea', 'savedGames', 'autoSave', 'autosave.tsvg'), 'wb') as f:
            f.write(b'partie')
        donnees_avant = empreintes(os.path.join(inst, 'donnees'))
        jar = os.path.join(inst, 'triplea-serveur', 'bin', 'game-headless.jar')
        cartes = os.path.join(inst, 'cartes')
        DEF = defauts['cartes']

        # a. première installation : dernière version, Java, quatre cartes
        code, out, urls = installer(dossier, ['', DEF, 'true'])
        if code or not os.path.isfile(jar) or io.open(os.path.join(inst, 'triplea-serveur', '.version')).read().strip() != TAG \
                or os.path.exists(os.path.join(inst, 'triplea-serveur', 'run_bot')) \
                or not os.path.isfile(os.path.join(inst, 'java', 'bin', 'java')) \
                or io.open(os.path.join(inst, 'java', '.version-temurin')).read().strip() != '25.0.4.1+1-LTS' \
                or sorted(os.listdir(cartes)) != sorted(n + '.zip' for n in QUATRE) \
                or urls[:2] != [LATEST, ZIP_URL % TAG] or CAT not in urls:
            soucis.append('installeur, première installation : code %d, %r, %r' % (code, urls, out))
        if not any('api.adoptium.net/v3/assets/latest/25/hotspot' in u and 'image_type=jre' in u and 'os=linux' in u for u in urls):
            soucis.append('installeur : Java 25 (version des classes 69 - 44) attendu sur api.adoptium.net : %r' % urls)
        # b. deuxième passage : rien à retélécharger (zips en attente d'extraction)
        code, out, urls = installer(dossier, ['', DEF, 'true'])
        if code or 'deja installe : rien a faire' not in out or 'Java 25.0.4.1+1-LTS (Eclipse Temurin) deja installe' not in out \
                or out.count('deja telechargee') != 4 or any('triplea-maps' in u or 'adoptium/' in u or 'game-headless' in u for u in urls):
            soucis.append('installeur, deuxième passage : rien à télécharger attendu : %r %r' % (urls, out))
        # le serveur extrait les zips (ZippedMapsExtractor) : on simule
        for n in QUATRE:
            os.remove(os.path.join(cartes, n + '.zip'))
            os.makedirs(os.path.join(cartes, n))
            with open(os.path.join(cartes, n, 'map.yml'), 'w') as f:
                f.write('ancienne')
        cartes_avant = empreintes(cartes)
        code, out, urls = installer(dossier, ['', DEF, 'true'])
        if code or out.count(': a jour.') != 4 or empreintes(cartes) != cartes_avant:
            soucis.append('installeur, cartes extraites et à jour : rien à faire : %r' % out)
        # c. une carte modifiée dans le catalogue : retéléchargée seulement si la mise à jour est cochée
        dates2 = dict(dates, world_war_ii_classic=5000)
        with open(os.path.join(fix, 'catalogue.json'), 'w') as f:
            f.write(catalogue(dates2))
        code, out, urls = installer(dossier, ['', DEF, 'false'])
        if code or any('triplea-maps' in u for u in urls) or 'mise a jour des cartes desactivee' not in out:
            soucis.append('installeur, mise à jour des cartes décochée : rien à télécharger : %r' % urls)
        code, out, urls = installer(dossier, ['', DEF, 'true'])
        if code or [u for u in urls if 'triplea-maps' in u] != ['https://github.com/triplea-maps/world_war_ii_classic/archive/refs/heads/master.zip'] \
                or not os.path.isfile(os.path.join(cartes, 'world_war_ii_classic.zip')) \
                or open(os.path.join(cartes, 'world_war_ii_classic', 'map.yml')).read() != 'ancienne':
            soucis.append('installeur, carte modifiée : seule elle est retéléchargée, en zip à côté : %r %r' % (urls, out))
        os.remove(os.path.join(cartes, 'world_war_ii_classic.zip'))
        code, out, urls = installer(dossier, ['', DEF, 'true'])
        if code or any('triplea-maps' in u for u in urls):
            soucis.append('installeur : la date de la carte retéléchargée doit être retenue : %r' % urls)
        # d. noms : affichage, inconnu, piégés, adresse étrangère, remontée de dossier
        PIEGES_CARTES = 'World War II Classic ; Pacific_1942, carte_piege, ../../etc, $(touch PWNED), inconnue_xyz, `touch PWNED2`'
        code, out, urls = installer(dossier, ['', PIEGES_CARTES, 'true'])
        if code or [u for u in urls if 'triplea-maps' in u] != ['https://github.com/triplea-maps/pacific_1942/archive/refs/heads/master.zip'] \
                or 'evil.example' in ' '.join(urls) or 'inconnue_xyz' not in out or 'carte_piege' not in out \
                or any('PWNED' in f for _, _, fs in os.walk(dossier) for f in fs) \
                or os.path.exists(os.path.join(dossier, 'etc')) or os.path.exists(os.path.join(inst, 'etc')):
            soucis.append('installeur, noms de cartes piégés : %r %r' % (urls, out))
        os.remove(os.path.join(cartes, 'pacific_1942.zip'))
        # e. version fixée (plus ancienne) : avertissement ; puis numéro piégé : on garde
        code, out, urls = installer(dossier, [ANCIEN, '', 'true'])
        if code or ZIP_URL % ANCIEN not in urls or LATEST in urls or 'plus ancienne' not in out \
                or io.open(os.path.join(inst, 'triplea-serveur', '.version')).read().strip() != ANCIEN \
                or 'Aucune carte demandee' not in out:
            soucis.append('installeur, version fixée : %r %r' % (urls, out))
        code, out, urls = installer(dossier, ['1.9; rm -rf /', '', 'true'])
        if code or any('game-headless' in u for u in urls) or 'On garde le serveur TripleA deja installe' not in out:
            soucis.append('installeur, numéro de version invalide : on garde l’installé : %r' % out)
        code, out, urls = installer(dossier, ['2026-08.16.15700', '', 'true'])
        if code or io.open(os.path.join(inst, 'triplea-serveur', '.version')).read().strip() != ANCIEN \
                or 'annonce la version' not in out or os.path.exists(os.path.join(inst, 'triplea-serveur.nouveau')):
            soucis.append('installeur, archive qui annonce une autre version : refus, serveur gardé : %r' % out)
        code, out, urls = installer(dossier, ['2025-01.15.1', '', 'true'])
        if code or 'introuvable' not in out:
            soucis.append('installeur, version inexistante avec un serveur installé : on le garde : %r' % out)
        # f. variables non remplacées par AMP : valeurs du dernier démarrage
        code, out, urls = installer(dossier, ['{{version}}', '{{cartes}}', '{{maj_cartes}}'],
                                    reglages='version=%s\r\ncartes=world_war_ii_v3\r\nmaj_cartes=false\r\n' % TAG)
        if code or ZIP_URL % TAG not in urls or LATEST in urls or 'world_war_ii_v3 : installee (mise a jour des cartes desactivee)' not in out.replace('Carte ', ''):
            soucis.append('installeur, variables non remplacées : valeurs de reglages-triplea.txt attendues : %r %r' % (urls, out))
        code, out, urls = installer(dossier, [], reglages='rien\n')
        if code or LATEST not in urls or out.count('Carte ') != 4:
            soucis.append('installeur sans argument : dernière version et cartes par défaut attendues : %r' % out)
        # g. échecs : réseau coupé avec tout installé (on garde) ; archive HTML (refus)
        avant_srv = empreintes(os.path.join(inst, 'triplea-serveur'))
        code, out, urls = installer(dossier, ['', DEF, 'true'], mode='echec')
        if code or empreintes(os.path.join(inst, 'triplea-serveur')) != avant_srv or 'on garde Java' not in out:
            soucis.append('installeur, réseau coupé avec tout installé : on garde (code 0) : %r' % out)
        code, out, urls = installer(dossier, [ANCIEN, DEF, 'true'], mode='html')
        if code or empreintes(os.path.join(inst, 'triplea-serveur')) != avant_srv or 'pas l\'archive du serveur' not in out:
            soucis.append('installeur, page HTML au lieu de l’archive : refus, serveur gardé : %r' % out)
        if empreintes(os.path.join(inst, 'donnees')) != donnees_avant:
            soucis.append('installeur : les données (sauvegardes) ont été modifiées')
        # h. instance neuve : réseau coupé = échec ; empreinte de Java fausse = refus
        neuf = os.path.join(dossier, 'neuf')
        os.makedirs(neuf)
        shutil.copytree(fix, os.path.join(neuf, 'fix'))
        code, out, urls = installer(neuf, ['', DEF, 'true'], mode='echec')
        if code != 1 or os.path.exists(os.path.join(neuf, 'triplea', 'triplea-serveur')):
            soucis.append('installeur, instance neuve sans réseau : échec attendu : %r' % out)
        with open(os.path.join(neuf, 'fix', 'java.json'), 'w') as f:
            f.write(java_json('0' * 64))
        code, out, urls = installer(neuf, ['', DEF, 'true'])
        if code != 1 or 'SHA-256' not in out or os.path.exists(os.path.join(neuf, 'triplea', 'java')):
            soucis.append('installeur, empreinte de Java fausse : refus attendu : %r' % out)
        with open(os.path.join(neuf, 'fix', 'java.json'), 'w') as f:
            f.write(java_json(somme).replace('https://github.com/adoptium/', 'https://evil.example/'))
        code, out, urls = installer(neuf, ['', DEF, 'true'])
        if code != 1 or any('evil.example' in u for u in urls):
            soucis.append('installeur, Java ailleurs que chez Adoptium : refus attendu : %r' % urls)
        print('ok   installeur                   dernière / fixée / piégée, Java SHA-256, cartes (nouvelle, à jour, modifiée, refusées), échecs, données intactes')
      except Exception as e:
        soucis.append('installeur : essai interrompu (%r)' % e)
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

# ── 7. regex de console ──────────────────────────────────────────────────────
# Lignes copiées de la sortie du vrai serveur 2026-10.16.15815 (Java 25, essai local du
# 11/10/2026 avec un faux lobby et un vrai jeu connecté par -Dtriplea.client=true) ;
# logback.xml du serveur : « %d{HH:mm:ss.SSS} [%t] %-5level %logger{36} - %msg%n ».
ESSAIS = [
    ('Console.AppReadyRegex', '21:47:57.077 [main] INFO  o.t.game.server.HeadlessGameServer - Waiting for users to connect.', {}),
    ('Console.AppReadyRegex', '09:12:00.001 [Thread-7] INFO  o.t.game.server.HeadlessGameServer - Waiting for users to connect.', {}),
    ('Console.UserJoinRegex', '21:48:09.845 [Decoder] INFO  games.strategy.net.ServerMessenger - Connection added to: Node(name=Testeur, address=/127.0.0.1, port=15006)', {'username': 'Testeur'}),
    ('Console.UserJoinRegex', '10:00:00.000 [Decoder] INFO  games.strategy.net.ServerMessenger - Connection added to: Node(name=Kevin (2), address=/203.0.113.7, port=51234)', {'username': 'Kevin (2)'}),
    ('Console.UserJoinRegex', '10:00:00.000 [Decoder] INFO  games.strategy.net.ServerMessenger - Connection added to: Node(name=hydro_cut, address=/2001:db8:0:0:0:0:0:1, port=1)', {'username': 'hydro_cut'}),
    ('Console.UserLeaveRegex', '21:48:42.851 [Thread-1] INFO  games.strategy.net.ServerMessenger - Connection removed: Node(name=Testeur, address=/127.0.0.1, port=15006)', {'username': 'Testeur'}),
    ('Console.UserLeaveRegex', '23:59:59.999 [pool-3-thread-1] INFO  games.strategy.net.ServerMessenger - Connection removed: Node(name=Kevin (2), address=/203.0.113.7, port=51234)', {'username': 'Kevin (2)'}),
]
for cle, ligne, attendu in ESSAIS:
    m = py(cles.get(cle) or '^$').search(ligne)
    if not m or any(m.group(k) != v for k, v in attendu.items()):
        soucis.append('%s ne reconnaît pas : %r' % (cle, ligne))
PIEGES = [
    ('Console.AppReadyRegex', '21:47:56.385 [main] INFO  o.t.game.server.HeadlessGameServer - Headless Start'),
    ('Console.AppReadyRegex', '21:49:07.912 [main] ERROR g.s.e.f.s.WatcherThreadMessaging$HeadlessWatcherThreadMessaging - Your computer is not reachable from the internet.'),
    ('Console.AppReadyRegex', 'TeamKit : Waiting for users to connect.'),
    ('Console.UserJoinRegex', '21:47:57.058 [main] INFO  g.s.engine.chat.ChatController - Chatter: Node(name=Bot_TeamKit_FR, address=/100.66.9.7, port=39001) is joining chat: games.strategy.engine.framework.ui.ServerStartup.CHAT_NAME'),
    ('Console.UserJoinRegex', '21:48:09.883 [pool-1-thread-1] INFO  g.s.engine.chat.ChatController - Chatter: Node(name=Testeur, address=/127.0.0.1, port=15006) is joining chat: games.strategy.engine.framework.ui.ServerStartup.CHAT_NAME'),
    ('Console.UserJoinRegex', '21:48:42.851 [Thread-1] INFO  games.strategy.net.ServerMessenger - Connection removed: Node(name=Testeur, address=/127.0.0.1, port=15006)'),
    ('Console.UserJoinRegex', '10:00:00.000 [x] WARN  games.strategy.net.ServerMessenger - Could not find node to remove: Node(name=Testeur, address=/127.0.0.1, port=15006)'),
    ('Console.UserLeaveRegex', '21:48:42.851 [Thread-1] INFO  g.s.engine.chat.ChatController - Chatter: Node(name=Testeur, address=/127.0.0.1, port=15006) has left chat: games.strategy.engine.framework.ui.ServerStartup.CHAT_NAME'),
    ('Console.UserLeaveRegex', '21:48:09.845 [Decoder] INFO  games.strategy.net.ServerMessenger - Connection added to: Node(name=Testeur, address=/127.0.0.1, port=15006)'),
    ('Console.UserLeaveRegex', 'TeamKit : Connection removed: Node(name=Testeur, address=/127.0.0.1, port=15006)'),
]
for cle, ligne in PIEGES:
    if py(cles[cle]).search(ligne):
        soucis.append('%s attrape une ligne qui n’est pas pour lui : %r' % (cle, ligne))
print('ok   console                      %d lignes du serveur, %d pièges' % (len(ESSAIS), len(PIEGES)))

print()
if soucis:
    print('%d problème(s) :' % len(soucis))
    print('\n'.join('  NON  ' + s for s in soucis))
    sys.exit(1)
print('Tout est bon.')
