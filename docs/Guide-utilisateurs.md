# Guide utilisateur — Casimir & Recherche Mairie Pierrefonds

Bienvenue sur le site **Demande à Casimir** : un outil pour interroger les documents et la vie municipale de **Pierrefonds (Oise)** grâce à la recherche sémantique et à un agent conversationnel.

---

## 1. Qu’est-ce que ce site ?

Ce site vous permet de :

- **Poser des questions en langage naturel** à l’agent **Casimir**, qui répond à partir des comptes rendus du Conseil municipal, du site de la mairie et d’autres sources indexées.
- **Rechercher** dans la base de connaissance (procès-verbaux, documents, pages web) avec une recherche par sens, pas seulement par mots exacts.
- **Consulter des statistiques** sur les séances du Conseil municipal (délibérations, votes, durée, présence des conseillers).
- **Accéder à la liste des sources** (PDF, documents) utilisées par Casimir et la recherche.

**Casimir** est un agent basé sur l’intelligence artificielle. Il a été alimenté avec les documents publics de la Mairie de Pierrefonds et des sites associés. Comme toute IA, il peut se tromper : les réponses s’appuient sur des **sources** que vous pouvez ouvrir pour vérifier.

---

## 2. Comprendre les outils (en quelques mots)

Pour mieux utiliser le site, voici des explications simples sur les notions clés.

### Qu’est-ce que la recherche sémantique ?

Avec une recherche **classique** (comme dans un moteur de recherche basique), on cherche les documents qui contiennent **exactement** les mots tapés. Si vous tapez « cantine », vous ne trouvez que les textes où le mot « cantine » apparaît.

Avec la **recherche sémantique**, le système comprend le **sens** de votre question. Il peut ainsi retrouver des passages qui parlent du même sujet même s’ils utilisent d’autres mots : « restauration scolaire », « repas à l’école », « tarifs des déjeuners », etc. C’est comme si le logiciel « comprenait » de quoi vous parlez et vous proposait les passages les plus proches de votre idée, pas seulement ceux qui répètent vos mots.

En résumé : la recherche sémantique cherche par **sens**, pas seulement par **mots exacts**.

### Qu’est-ce qu’une base vectorielle ?

Derrière la recherche sémantique, les textes (vos questions et les extraits des documents) sont transformés en **résumés numériques de leur sens** — on parle de « vecteurs » ou d’« embeddings ». Une **base vectorielle** est simplement l’ensemble de ces résumés, associés à chaque passage des documents (procès-verbaux, pages web, etc.).

Quand vous faites une recherche, votre question est elle aussi transformée en un tel résumé. Le système compare ensuite ce résumé à ceux de tous les passages et renvoie ceux qui sont **les plus proches en sens** — un peu comme un moteur qui dirait : « Ce passage parle vraiment du même sujet que votre question. »

En résumé : la base vectorielle est le **catalogue des sens** des textes indexés ; elle permet de retrouver rapidement les passages qui correspondent le mieux à ce que vous cherchez.

### Qu’est-ce qu’un agent (Casimir) ?

Un **agent**, dans ce contexte, est un programme qui **agit pour vous** à partir de votre question : il ne se contente pas d’afficher une liste de textes, il **lit** les passages pertinents et **rédige une réponse** en français, comme un assistant qui aurait parcouru les documents à votre place.

Casimir fait exactement cela : il utilise la recherche sémantique pour trouver les extraits les plus utiles, puis un **modèle de langage** (voir ci-dessous) pour produire une phrase ou un paragraphe qui répond à votre question en s’appuyant uniquement sur ces extraits. Vous obtenez donc une **réponse synthétique** avec des **liens vers les sources**, au lieu de devoir lire vous-même une longue liste de résultats.

En résumé : l’agent est un **intermédiaire intelligent** qui cherche dans les documents et vous formule une réponse à partir de ce qu’il y a trouvé.

### Quel modèle est utilisé ?

Le site utilise **deux types de modèles** (programmes d’intelligence artificielle), chacun avec un rôle précis :

1. **Pour la recherche** (retrouver les bons passages) : un modèle spécialisé dans la **compréhension du sens** des textes en plusieurs langues. Il sert à construire la base vectorielle et à comparer votre question aux passages. Vous ne le voyez pas directement ; il travaille « sous le capot » pour que la recherche sémantique fonctionne.

2. **Pour les réponses de Casimir** : un **modèle de langage** (type « grand modèle conversationnel ») fourni par Groq, qui sait lire des textes et rédiger une réponse en français. Casimir lui envoie votre question et les passages trouvés, et le modèle produit la phrase ou le paragraphe que vous lisez. Ce type de modèle est le même que celui qui équipe les assistants vocaux ou les chatbots : il est entraîné sur énormément de textes pour parler de façon naturelle, mais ici on le limite strictement aux **sources** fournies (procès-verbaux, site mairie, etc.) pour éviter qu’il invente des informations.

En résumé : un modèle sert à **trouver** les bons textes (recherche sémantique), l’autre à **rédiger** la réponse à partir de ces textes (agent Casimir). Les deux sont des programmes d’IA, utilisés de façon transparente pour vous.

---

## 3. Accéder au site

- **Site principal (Casimir)** : [https://mymairie-ksbry6thyvm8uddujy289c.streamlit.app/](https://mymairie-ksbry6thyvm8uddujy289c.streamlit.app/)
- **Contact** : [casimir.pierrefonds@outlook.com](mailto:casimir.pierrefonds@outlook.com)

Le bandeau en haut de page affiche la date de déploiement, votre adresse IP (pour information) et le nombre de recherches effectuées aujourd’hui ainsi que le nombre de recherches restantes pour vous (voir section 9).

---

## 4. Page d’accueil

Sur la page d’accueil, quatre cartes vous permettent d’accéder aux différentes fonctionnalités :

| Carte | Description |
|-------|-------------|
| **Interroger l’Agent Casimir** | Posez une question en langage naturel ; Casimir synthétise une réponse à partir des documents. |
| **Recherche dans la base de connaissance** | Recherche sémantique dans les comptes rendus et toute la base, avec filtres et suggestions. |
| **Statistiques des séances du Conseil Municipal** | Graphiques : délibérations par année, types de vote, durée des séances, présence des conseillers. |
| **Sources et Documents** | Liste des sources (PDF, etc.) utilisées par Casimir et la recherche. |

Cliquez sur **« Accéder → »** sur la carte souhaitée.

En haut de page : **Accueil** (retour à cette page), **À propos** (présentation de Casimir), et l’adresse e-mail de contact.

---

## 5. Interroger l’Agent Casimir

1. Depuis l’accueil, cliquez sur **« Interroger l’Agent Casimir »**.
2. Saisissez votre question dans la zone de texte (ex. : *« Comment ont évolué les tarifs de la cantine scolaire ? »*, *« Quels travaux de voirie ont été votés ? »*).
3. Vous pouvez aussi cliquer sur un **exemple** proposé pour lancer directement une recherche.
4. Cliquez sur **« Obtenir une réponse »**.

Casimir :
- recherche les passages pertinents dans la base ;
- génère une réponse en français, en s’appuyant **uniquement** sur ces passages ;
- affiche des **références [1], [2], …** qui deviennent des liens cliquables vers les documents sources (PDF ou page web).

Sous la réponse, un encadré **« X passages consultés »** permet de voir les extraits utilisés et d’ouvrir chaque source. Les scores de pertinence (vert / orange / rouge) indiquent à quel point le passage correspond à votre question.

**Conseils :**
- Formulez des questions précises pour des réponses plus ciblées.
- Pour les montants (travaux, budget), les chiffres exacts se trouvent dans les procès-verbaux sur [mairie-pierrefonds.fr](https://www.mairie-pierrefonds.fr/vie-municipale/conseil-municipal/#proces-verbal) ; Casimir peut vous orienter vers les bons documents.

---

## 6. Recherche dans la base de connaissance

1. Depuis l’accueil, cliquez sur **« Recherche dans la base de connaissance »**.
2. La **barre latérale** (à gauche) propose des **thèmes** : Convention/Contrat, Budget/Finances, École/Scolaire, Travaux/Voirie, Forêt/Bois, Urbanisme/Permis, etc. Un clic sur un thème remplit la requête avec des mots-clés associés.
3. Vous pouvez :
   - **Filtrer par année(s)** : sélectionnez une ou plusieurs années (sinon toutes sont prises en compte).
   - **Choisir le nombre de résultats** (par défaut 15).
   - **Activer « Mot(s) exact(s) »** : seuls les passages contenant vraiment le ou les mots saisis sont retournés (recherche plus stricte).
4. Saisissez votre requête dans le champ **« Recherche sémantique »** ou utilisez les **suggestions** (Bois D’Haucourt, Vertefeuille, permis de construire, etc.).
5. Validez : les résultats s’affichent avec un extrait, la date, le fichier source et un **bouton « Ouvrir »** pour consulter le PDF.

La recherche est **sémantique** : elle comprend le sens de votre requête, pas seulement les mots exacts. Si vous n’obtenez rien avec « Mot(s) exact(s) » activé, essayez en le désactivant.

---

## 7. Statistiques des séances du Conseil Municipal

Cette section affiche des **graphiques** construits à partir des procès-verbaux indexés :

- **Séances et délibérations par année** (barres).
- **Répartition des types de vote** (unanimité, vote avec décompte, etc.).
- **Durée des séances** : moyenne, plus longue, plus courte ; évolution par année ; durée de chaque séance.
- **Présence des conseillers** (nombre de séances présentes).
- **Délibérations par thème**.
- **Votes avec opposition ou abstention** (liste détaillée).

Vous pouvez **filtrer par année(s)** pour restreindre la période affichée.

---

## 8. Sources et Documents

La section **« Sources et Documents »** liste les documents disponibles (PDF, fichiers .md) utilisés par Casimir et la recherche, triés par date. Chaque entrée est cliquable pour ouvrir le document.

La **source officielle** des procès-verbaux du Conseil municipal est indiquée : [mairie-pierrefonds.fr — Procès-verbaux du Conseil Municipal](https://www.mairie-pierrefonds.fr/vie-municipale/conseil-municipal/#proces-verbal).

---

## 9. Limites d’utilisation

- **Recherches par heure** : pour préserver le service, le nombre de recherches (Agent Casimir + Recherche dans la base) est limité à **5 par heure** par adresse IP. Au-delà, un message vous invite à réessayer plus tard.
- Le bandeau en haut affiche le nombre de recherches **restantes** pour vous (ou « ∞ » si la limite ne s’applique pas).
- Casimir peut être temporairement indisponible (quota des fournisseurs d’IA) ; dans ce cas, privilégiez la **Recherche dans la base** pour consulter les passages pertinents.

---

## 10. À propos de Casimir

Casimir est un agent créé à titre expérimental pour :
- connaître la vie de la commune de Pierrefonds à partir des documents publics (Mairie, sites web, journaux) ;
- répondre aux questions des utilisateurs en s’appuyant sur ces sources.

Il est hébergé sur Streamlit et utilise des modèles d’IA (ex. via Groq). Les réponses sont à considérer avec l’aide des **sources** fournies ; pour les informations officielles et à jour (horaires, tarifs, procédures), consultez toujours le site de la Mairie : [mairie-pierrefonds.fr](https://www.mairie-pierrefonds.fr).

---

## 11. Résumé rapide

| Besoin | Où aller |
|--------|----------|
| Poser une question en langage naturel | **Interroger l’Agent Casimir** |
| Chercher un mot, un thème, une délibération | **Recherche dans la base de connaissance** |
| Voir des graphiques sur le Conseil municipal | **Statistiques des séances** |
| Consulter la liste des documents indexés | **Sources et Documents** |
| Contacter l’équipe Casimir | [casimir.pierrefonds@outlook.com](mailto:casimir.pierrefonds@outlook.com) |

---

## 12. Documentation technique (développeurs / mainteneurs)

Pour une description technique détaillée du projet (architecture, pipeline d’indexation, recherche sémantique, agent RAG) :

- **[Architecture technique](Architecture-technique.md)** — Structure du projet, pipeline (ALL.bat, fetch_sites, ingest, stats_extract), déploiement, dépendances et variables d’environnement.
- **[Recherche et agent RAG](Recherche-et-agent-RAG.md)** — Modèle d’embeddings, chunking, base vectorielle, recherche hybride pour l’agent, prompt système, API Groq, rate limiting, sécurité.

---

*Documentation générée pour les utilisateurs du site Casimir — Mairie Pierrefonds (Oise).*
